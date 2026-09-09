import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from token_runtime.cli import build_parser, main
from token_runtime.config import TokenConfig, save_config


class QuietHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class CliTests(unittest.TestCase):
    def test_parser_exposes_product_commands(self):
        parser = build_parser()
        for command in (
            "serve", "status", "doctor", "optimize",
            "benchmark", "install", "uninstall",
        ):
            args = parser.parse_args([command])
            self.assertEqual(args.command, command)

    def test_optimize_reads_stdin_and_preserves_current_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            save_config(TokenConfig(
                upstream="http://127.0.0.1:9",
                host="127.0.0.1", port=8788,
                state_dir=str(Path(tmp) / "state"),
            ), config_path)
            repeated = "old assistant history line with enough bytes to reduce"
            payload = {"model": "x", "messages": [
                {"role": "assistant", "content": "\n".join([repeated] * 30)},
                {"role": "user", "content": "current task exact"},
            ]}
            out = io.StringIO()
            code = main([
                "optimize", "--config", str(config_path),
                "--endpoint", "/v1/chat/completions",
            ], stdin=io.StringIO(json.dumps(payload)), stdout=out)
            self.assertEqual(code, 0)
            optimized = json.loads(out.getvalue())
            self.assertEqual(optimized["messages"][1]["content"], "current task exact")
            self.assertLess(len(out.getvalue()), len(json.dumps(payload)))

    def test_doctor_reports_config_state_gateway_and_upstream_health(self):
        upstream = start_server()
        gateway = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config_path = Path(tmp) / "config.json"
                save_config(TokenConfig(
                    upstream=f"http://127.0.0.1:{upstream.server_port}",
                    host="127.0.0.1", port=gateway.server_port,
                    state_dir=str(Path(tmp) / "state"),
                ), config_path)
                out = io.StringIO()
                code = main([
                    "doctor", "--config", str(config_path)
                ], stdout=out)
                report = json.loads(out.getvalue())
                self.assertEqual(code, 0)
                self.assertTrue(report["config_ok"])
                self.assertTrue(report["state_ok"])
                self.assertTrue(report["gateway_reachable"])
                self.assertTrue(report["upstream_reachable"])
        finally:
            upstream.shutdown(); upstream.server_close()
            gateway.shutdown(); gateway.server_close()


if __name__ == "__main__":
    unittest.main()


class CliProductFlowTests(unittest.TestCase):
    def test_benchmark_reports_before_after_and_fidelity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            save_config(TokenConfig(
                upstream="http://127.0.0.1:9", state_dir=str(root / "state")
            ), config_path)
            repeated = "historical repeated line with enough bytes to reduce"
            fixture = root / "cases.json"
            fixture.write_text(json.dumps({"cases": [{
                "name": "safe",
                "blocks": [
                    {"id": "old", "kind": "assistant", "text": "\n".join([repeated] * 30), "turn_index": 0},
                    {"id": "u", "kind": "user", "text": "current task", "turn_index": 1},
                ],
            }]}))
            out = io.StringIO()
            code = main(["benchmark", "--config", str(config_path), "--file", str(fixture)], stdout=out)
            report = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertGreater(report["baseline_estimated_tokens"], report["optimized_estimated_tokens"])
            self.assertTrue(report["all_protected_fidelity"])
            self.assertTrue(report["all_recoverable"])

    def test_install_dry_run_does_not_mutate_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / ".env"
            original = b"OPENAI_API_KEY=secret\n"
            env.write_bytes(original)
            config_path = root / "config.json"
            save_config(TokenConfig(
                upstream="http://127.0.0.1:9999", state_dir=str(root / "state")
            ), config_path)
            out = io.StringIO()
            code = main([
                "install", "--config", str(config_path), "--root", str(root), "--dry-run"
            ], stdout=out)
            payload = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(env.read_bytes(), original)
            self.assertEqual(payload["mode"], "dry_run")
            self.assertEqual(payload["detected"], 1)
            self.assertEqual(payload["applied"], 0)

    def test_install_then_uninstall_restores_env_without_copying_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / ".env"
            original = b"OPENAI_API_KEY=SECRET_SENTINEL\nOTHER=1\n"
            env.write_bytes(original)
            config_path = root / "config.json"
            save_config(TokenConfig(
                upstream="http://127.0.0.1:9999", state_dir=str(root / "state")
            ), config_path)
            self.assertEqual(main([
                "install", "--config", str(config_path), "--root", str(root)
            ], stdout=io.StringIO()), 0)
            self.assertIn(b"TOKEN MANAGED", env.read_bytes())
            self.assertEqual(main([
                "uninstall", "--config", str(config_path), "--root", str(root)
            ], stdout=io.StringIO()), 0)
            self.assertEqual(env.read_bytes(), original)
            copies = [p for p in root.rglob("*") if p.is_file() and p != env and b"SECRET_SENTINEL" in p.read_bytes()]
            self.assertEqual(copies, [])

    def test_install_can_bootstrap_missing_config_from_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENAI_API_KEY=sentinel\n", encoding="utf-8")
            config_path = root / "token-config.json"
            out = io.StringIO()
            code = main([
                "install", "--config", str(config_path), "--root", str(root),
                "--upstream", "http://127.0.0.1:9999"
            ], stdout=out)
            self.assertEqual(code, 0)
            self.assertTrue(config_path.exists())
            data = json.loads(config_path.read_text())
            self.assertEqual(data["upstream"], "http://127.0.0.1:9999")
            self.assertEqual(data["host"], "127.0.0.1")
            self.assertTrue(data["state_dir"])
            self.assertIn("TOKEN MANAGED", (root / ".env").read_text())


class CliCodexIntegrationTests(unittest.TestCase):
    def test_install_and_uninstall_codex_provider_are_transactional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex = root / ".codex" / "config.toml"
            codex.parent.mkdir()
            original = b'[model_providers.router9]\nbase_url = "http://127.0.0.1:20128/v1"\nwire_api = "responses"\n'
            codex.write_bytes(original)
            config_path = root / "token-config.json"
            save_config(TokenConfig(upstream="http://127.0.0.1:20128", host="127.0.0.1", port=8788, state_dir=str(root / "state")), config_path)
            out = io.StringIO()
            self.assertEqual(main(["install", "--config", str(config_path), "--root", str(root)], stdout=out), 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report["applied"], 1)
            self.assertEqual(report["sidecars"], 0)
            self.assertEqual(report["integrations"][0]["activation"], "managed_gateway")
            self.assertIn(b'base_url = "http://127.0.0.1:8788/v1"', codex.read_bytes())
            self.assertEqual(main(["uninstall", "--config", str(config_path), "--root", str(root)], stdout=io.StringIO()), 0)
            self.assertEqual(codex.read_bytes(), original)
