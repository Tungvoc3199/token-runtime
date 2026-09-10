import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from token_runtime.engine import OptimizationEngine
from token_runtime.gateway import GatewayCore, build_server
from token_runtime.metrics import MetricsStore
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


class BrokenEngine:
    def optimize(self, envelope):
        raise RuntimeError("boom")


def make_core(tmp, engine=None):
    metrics = MetricsStore(Path(tmp) / "metrics.db")
    if engine is None:
        engine = OptimizationEngine(
            planner=ContextPlanner(),
            store=RecoveryStore(Path(tmp) / "recovery.db"),
        )
    return GatewayCore(engine=engine, metrics=metrics), metrics


class GatewayCoreTests(unittest.TestCase):
    def test_supported_chat_payload_is_optimized(self):
        with tempfile.TemporaryDirectory() as tmp:
            core, _ = make_core(tmp)
            line = "redundant assistant history line with enough bytes to matter"
            payload = {"model": "x", "messages": [
                {"role": "assistant", "content": "\n".join([line] * 20)},
                {"role": "user", "content": "current task"},
            ]}
            raw = json.dumps(payload).encode()
            prepared = core.prepare("/v1/chat/completions", raw)
            self.assertTrue(prepared.optimized)
            self.assertLess(len(prepared.body), len(raw))
            changed = json.loads(prepared.body)
            self.assertEqual(changed["messages"][1]["content"], "current task")

    def test_malformed_json_is_exact_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            core, _ = make_core(tmp)
            raw = b'{"broken":'
            prepared = core.prepare("/v1/responses", raw)
            self.assertFalse(prepared.optimized)
            self.assertIs(prepared.body, raw)
            self.assertIn("invalid_json", prepared.reasons)

    def test_unsupported_endpoint_is_exact_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            core, _ = make_core(tmp)
            raw = b"opaque bytes"
            prepared = core.prepare("/custom", raw)
            self.assertIs(prepared.body, raw)
            self.assertIn("unsupported_endpoint", prepared.reasons)

    def test_internal_engine_error_is_exact_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            core, _ = make_core(tmp, engine=BrokenEngine())
            raw = b'{"model":"x","messages":[{"role":"user","content":"hello"}]}'
            prepared = core.prepare("/v1/chat/completions", raw)
            self.assertIs(prepared.body, raw)
            self.assertIn("fallback_internal_error", prepared.reasons)


class GatewayHttpTests(unittest.TestCase):
    def test_forwards_auth_without_persisting_secret_and_preserves_response(self):
        captured = {}

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                captured["authorization"] = self.headers.get("Authorization")
                captured["body"] = self.rfile.read(length)
                response = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        with tempfile.TemporaryDirectory() as tmp:
            core, metrics = make_core(tmp)
            gateway = build_server(
                "127.0.0.1", 0,
                upstream=f"http://127.0.0.1:{upstream.server_port}",
                core=core,
            )
            gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
            gateway_thread.start()
            try:
                payload = b'{"model":"x","messages":[{"role":"user","content":"hello"}]}'
                request = Request(
                    f"http://127.0.0.1:{gateway.server_port}/v1/chat/completions",
                    data=payload,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + "SECRET_SENTINEL"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    body = response.read()
                self.assertEqual(body, b'{"ok":true}')
                self.assertEqual(captured["authorization"], "Bearer " + "SECRET_SENTINEL")
                self.assertEqual(captured["body"], payload)
                self.assertEqual(metrics.summary()["requests"], 1)
                self.assertNotIn(b"SECRET_SENTINEL", (Path(tmp) / "metrics.db").read_bytes())
            finally:
                gateway.shutdown()
                gateway.server_close()
                upstream.shutdown()
                upstream.server_close()


if __name__ == "__main__":
    unittest.main()
