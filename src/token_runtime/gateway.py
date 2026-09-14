from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .metrics import MetricsStore
from .protocol_registry import (
    ProtocolAdapterRegistry,
    default_protocol_adapter_registry,
)
from .model import OptimizationDecision


_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    body: bytes
    optimized: bool
    reasons: tuple[str, ...]
    adapter: str | None = None


class GatewayCore:
    def __init__(
        self,
        *,
        engine,
        metrics: MetricsStore,
        registry: ProtocolAdapterRegistry | None = None,
    ):
        self.engine = engine
        self.metrics = metrics
        self.registry = (
            registry if registry is not None else default_protocol_adapter_registry()
        )

    def prepare(self, path: str, raw_body: bytes) -> PreparedRequest:
        started = time.perf_counter()
        adapter = self.registry.resolve(path)
        if adapter is None:
            prepared = PreparedRequest(raw_body, False, ("unsupported_endpoint",), None)
            self._record(prepared, None, None, None, started)
            return prepared

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON request must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            prepared = PreparedRequest(raw_body, False, ("invalid_json",), adapter.name)
            self._record(prepared, None, None, None, started)
            return prepared

        try:
            envelope = adapter.parse(payload)
            result = self.engine.optimize(envelope)
            if result.decision is OptimizationDecision.OPTIMIZE:
                serialized = adapter.serialize(result.envelope)
                body = json.dumps(
                    serialized, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                prepared = PreparedRequest(body, True, result.reasons, adapter.name)
            else:
                prepared = PreparedRequest(raw_body, False, result.reasons, adapter.name)
            self._record(prepared, result, payload, adapter.name, started)
            return prepared
        except Exception:
            prepared = PreparedRequest(
                raw_body, False, ("fallback_internal_error",), adapter.name
            )
            self._record(prepared, None, payload, adapter.name, started)
            return prepared

    def _record(self, prepared, result, payload, adapter_name, started) -> None:
        before = getattr(result, "before_estimated_tokens", None)
        after = getattr(result, "after_estimated_tokens", None)
        model = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(model, str) or not _SAFE_LABEL_RE.fullmatch(model):
            model = None
        event = {
            "decision": "optimize" if prepared.optimized else "bypass",
            "adapter": adapter_name,
            "model": model,
            "before_input_tokens": before,
            "after_input_tokens": after,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "reason_codes": prepared.reasons,
            "reducer_ids": (),
        }
        self.metrics.record(event)


def _request_headers(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    return {
        key: value
        for key, value in handler.headers.items()
        if key.lower() not in _HOP_HEADERS
    }


def _write_upstream_response(handler, response) -> None:
    handler.send_response(response.status)
    for key, value in response.headers.items():
        if key.lower() not in _HOP_HEADERS:
            handler.send_header(key, value)
    handler.end_headers()
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        handler.wfile.write(chunk)


def build_server(host: str, port: int, *, upstream: str, core: GatewayCore):
    upstream_base = upstream.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            prepared = core.prepare(self.path, raw_body)
            request = Request(
                upstream_base + self.path,
                data=prepared.body,
                headers=_request_headers(self),
                method="POST",
            )
            try:
                with urlopen(request, timeout=60) as response:
                    _write_upstream_response(self, response)
            except HTTPError as response:
                _write_upstream_response(self, response)

        def log_message(self, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str, port: int, *, upstream: str, core: GatewayCore) -> None:
    server = build_server(host, port, upstream=upstream, core=core)
    try:
        server.serve_forever()
    finally:
        server.server_close()
