from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from urllib.parse import urlparse

from .benchmark import BenchmarkCase, benchmark_cases
from .config import (
    TokenConfig,
    default_config_path,
    default_state_dir,
    load_config,
    save_config,
)
from .engine import OptimizationEngine
from .gateway import GatewayCore, serve
from .integrations import (
    apply_plan,
    detect_integrations,
    plan_install,
    uninstall_integration,
)
from .metrics import MetricsStore
from .model import ContextBlock, RequestEnvelope
from .planner import ContextPlanner
from .store import RecoveryStore
from .terminal_ui import render_welcome


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token")
    subs = parser.add_subparsers(dest="command")
    for name in ("serve", "status", "doctor"):
        sub = subs.add_parser(name)
        _add_config_argument(sub)

    optimize = subs.add_parser("optimize")
    _add_config_argument(optimize)
    optimize.add_argument("--endpoint", default="/v1/responses")

    benchmark = subs.add_parser("benchmark")
    _add_config_argument(benchmark)
    benchmark.add_argument("--file", default=None)

    install = subs.add_parser("install")
    _add_config_argument(install)
    install.add_argument("--root", default=None)
    install.add_argument("--upstream", default=None)
    install.add_argument("--dry-run", action="store_true")

    uninstall = subs.add_parser("uninstall")
    _add_config_argument(uninstall)
    uninstall.add_argument("--root", default=None)
    uninstall.add_argument("--dry-run", action="store_true")

    return parser


def _config_path(value: str | None) -> Path:
    return Path(value) if value else default_config_path()


def _runtime(config):
    state = Path(config.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    metrics = MetricsStore(state / "metrics.db")
    engine = OptimizationEngine(
        planner=ContextPlanner(),
        store=RecoveryStore(state / "recovery.db"),
    )
    return GatewayCore(engine=engine, metrics=metrics), metrics


def _read_input_bytes(stdin) -> bytes:
    if hasattr(stdin, "buffer"):
        return stdin.buffer.read()
    value = stdin.read()
    return value.encode("utf-8") if isinstance(value, str) else value

def _reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def doctor_report(config_path: Path) -> dict[str, bool]:
    report = {
        "config_ok": False,
        "state_ok": False,
        "gateway_reachable": False,
        "upstream_reachable": False,
    }
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        return report
    report["config_ok"] = True

    state = Path(config.state_dir)
    try:
        state.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=state):
            pass
        RecoveryStore(state / "recovery.db")
        MetricsStore(state / "metrics.db")
        report["state_ok"] = True
    except OSError:
        return report

    report["gateway_reachable"] = _reachable(config.host, config.port)
    parsed = urlparse(config.upstream)
    upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    report["upstream_reachable"] = bool(parsed.hostname) and _reachable(
        parsed.hostname, upstream_port
    )
    return report

def _write_json(stdout, value) -> None:
    stdout.write(json.dumps(value, sort_keys=True) + "\n")


def _root_path(value: str | None) -> Path:
    return Path(value).expanduser() if value else Path.home()


def _install_config(path: Path, args, root: Path) -> TokenConfig:
    if path.exists():
        return load_config(path)
    if not args.upstream:
        raise FileNotFoundError("TOKEN config is missing; pass --upstream to bootstrap it")
    config = TokenConfig(
        upstream=args.upstream,
        host="127.0.0.1",
        port=8788,
        state_dir=str(default_state_dir(root)),
    )
    if not args.dry_run:
        save_config(config, path)
    return config


def _load_benchmark_cases(path: str | Path) -> list[BenchmarkCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("benchmark file must contain a cases array")
    cases: list[BenchmarkCase] = []
    for index, item in enumerate(data["cases"]):
        if not isinstance(item, dict) or not isinstance(item.get("blocks"), list):
            raise ValueError(f"benchmark case {index} is invalid")
        blocks = []
        for block_index, raw in enumerate(item["blocks"]):
            if not isinstance(raw, dict):
                raise ValueError(f"benchmark block {index}:{block_index} is invalid")
            blocks.append(ContextBlock(
                id=str(raw.get("id", f"b{block_index}")),
                kind=str(raw["kind"]),
                text=str(raw["text"]),
                role=raw.get("role"),
                turn_index=int(raw.get("turn_index", 0)),
            ))
        cases.append(BenchmarkCase(str(item.get("name", f"case-{index}")), RequestEnvelope(tuple(blocks))))
    return cases


def main(argv=None, *, stdin=None, stdout=None) -> int:
    args = build_parser().parse_args(argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if args.command is None:
        render_welcome(stdout)
        return 0
    path = _config_path(args.config)

    if args.command == "install":
        root = _root_path(args.root)
        config = _install_config(path, args, root)
        gateway_url = f"http://{config.host}:{config.port}/v1"
        integrations = detect_integrations(root)
        rows = []
        active = sidecars = blocked = 0
        for integration in integrations:
            plan = plan_install(integration, gateway_url=gateway_url)
            result = apply_plan(plan, apply=not args.dry_run)
            activation = "managed_gateway" if plan.mode in {"managed_block", "managed_toml"} else "detected_sidecar_only"
            if not plan.safe_to_apply:
                blocked += 1
            elif not args.dry_run and activation == "managed_gateway":
                active += 1
            elif not args.dry_run:
                sidecars += 1
            rows.append({
                "kind": integration.kind,
                "activation": activation,
                "changed": result.changed,
                "reason": result.reason,
                "target": str(result.target_path),
            })
        _write_json(stdout, {
            "mode": "dry_run" if args.dry_run else "apply",
            "detected": len(integrations),
            "applied": active,
            "sidecars": sidecars,
            "blocked": blocked,
            "integrations": rows,
        })
        return 1 if blocked else 0

    if args.command == "uninstall":
        root = _root_path(args.root)
        integrations = detect_integrations(root)
        rows = []
        removed = 0
        for integration in integrations:
            result = uninstall_integration(integration, apply=not args.dry_run)
            if not args.dry_run and result.changed:
                removed += 1
            rows.append({
                "kind": integration.kind,
                "changed": result.changed,
                "reason": result.reason,
                "target": str(result.target_path),
            })
        _write_json(stdout, {
            "mode": "dry_run" if args.dry_run else "apply",
            "detected": len(integrations),
            "removed": removed,
            "integrations": rows,
        })
        return 0

    if args.command == "doctor":
        report = doctor_report(path)
        payload = dict(report)
        if not report["config_ok"]:
            payload["next_step"] = "token install --upstream <UPSTREAM_URL>"
        _write_json(stdout, payload)
        return 0 if all(report.values()) else 1

    config = load_config(path)
    if args.command == "serve":
        core, _ = _runtime(config)
        serve(config.host, config.port, upstream=config.upstream, core=core)
        return 0
    if args.command == "status":
        _, metrics = _runtime(config)
        _write_json(stdout, metrics.summary())
        return 0
    if args.command == "optimize":
        core, _ = _runtime(config)
        prepared = core.prepare(args.endpoint, _read_input_bytes(stdin))
        stdout.write(prepared.body.decode("utf-8", errors="surrogateescape"))
        return 0
    if args.command == "benchmark":
        if not args.file:
            raise ValueError("benchmark requires --file")
        core, _ = _runtime(config)
        report = benchmark_cases(_load_benchmark_cases(args.file), core.engine)
        all_fidelity = all(row.protected_byte_fidelity == 1.0 for row in report.cases)
        all_recoverable = all(row.recoverable for row in report.cases)
        _write_json(stdout, {
            "baseline_estimated_tokens": report.baseline_estimated_tokens,
            "optimized_estimated_tokens": report.optimized_estimated_tokens,
            "total_saved_pct": report.total_saved_pct,
            "eligible_saved_pct": report.eligible_saved_pct,
            "optimized_count": report.optimized_count,
            "bypass_count": report.bypass_count,
            "all_protected_fidelity": all_fidelity,
            "all_recoverable": all_recoverable,
            "offline_gate": bool(report.eligible_saved_pct >= 20 and all_fidelity and all_recoverable),
            "cases": [{
                "name": row.name,
                "decision": row.decision,
                "saved_pct": row.saved_pct,
                "reasons": row.reasons,
                "protected_byte_fidelity": row.protected_byte_fidelity,
                "recoverable": row.recoverable,
            } for row in report.cases],
        })
        return 0
    return 2
