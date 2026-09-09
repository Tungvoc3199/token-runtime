from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping


_ALLOWED = {
    "decision", "adapter", "provider", "model",
    "before_input_tokens", "after_input_tokens",
    "provider_input_tokens", "provider_output_tokens", "cached_tokens",
    "latency_ms", "reducer_ids", "reason_codes",
}


class MetricsStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "ts REAL NOT NULL, decision TEXT NOT NULL, adapter TEXT, provider TEXT, model TEXT, "
                "before_input_tokens INTEGER, after_input_tokens INTEGER, provider_input_tokens INTEGER, "
                "provider_output_tokens INTEGER, cached_tokens INTEGER, latency_ms REAL, "
                "reducer_ids TEXT NOT NULL, reason_codes TEXT NOT NULL)"
            )
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def record(self, event: Mapping[str, Any]) -> None:
        unknown = set(event) - _ALLOWED
        if unknown:
            raise ValueError(f"unsupported telemetry fields: {sorted(unknown)}")
        decision = event.get("decision")
        if decision not in {"optimize", "bypass"}:
            raise ValueError("decision must be optimize or bypass")

        values = (
            time.time(), decision, event.get("adapter"), event.get("provider"), event.get("model"),
            event.get("before_input_tokens"), event.get("after_input_tokens"),
            event.get("provider_input_tokens"), event.get("provider_output_tokens"),
            event.get("cached_tokens"), event.get("latency_ms"),
            json.dumps(tuple(event.get("reducer_ids", ()))),
            json.dumps(tuple(event.get("reason_codes", ()))),
        )
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def summary(self) -> dict[str, int | float]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN decision='optimize' THEN 1 ELSE 0 END), "
                "COALESCE(SUM(before_input_tokens),0), COALESCE(SUM(after_input_tokens),0), "
                "COALESCE(SUM(provider_input_tokens),0), COALESCE(SUM(provider_output_tokens),0), "
                "COALESCE(SUM(cached_tokens),0) FROM events"
            ).fetchone()
        requests, optimized, before, after, provider_in, provider_out, cached = row
        saved = before - after
        pct = round(saved * 100 / before, 1) if before else 0.0
        return {
            "requests": requests,
            "optimized": optimized or 0,
            "bypassed": requests - (optimized or 0),
            "estimated_input_before": before,
            "estimated_input_after": after,
            "estimated_input_saved": saved,
            "estimated_input_saved_pct": pct,
            "provider_input_tokens": provider_in,
            "provider_output_tokens": provider_out,
            "cached_tokens": cached,
        }
