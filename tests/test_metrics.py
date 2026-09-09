import os
import stat
import tempfile
import unittest
from pathlib import Path

from token_runtime.metrics import MetricsStore


class MetricsTests(unittest.TestCase):
    def test_records_allowlisted_numeric_and_label_fields_and_summarizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MetricsStore(Path(tmp) / "metrics.db")
            store.record({
                "decision": "optimize",
                "adapter": "responses",
                "provider": "openai-compatible",
                "model": "vscode-debug",
                "before_input_tokens": 1000,
                "after_input_tokens": 700,
                "provider_input_tokens": 700,
                "provider_output_tokens": 50,
                "cached_tokens": 200,
                "latency_ms": 123.4,
                "reducer_ids": ("repeat_runs_v1",),
                "reason_codes": ("optimized",),
            })
            summary = store.summary()
            self.assertEqual(summary["requests"], 1)
            self.assertEqual(summary["optimized"], 1)
            self.assertEqual(summary["estimated_input_saved"], 300)
            self.assertEqual(summary["provider_input_tokens"], 700)

    def test_rejects_non_allowlisted_sensitive_payload_fields(self):
        banned = ("prompt", "body", "headers", "authorization", "api_key")
        with tempfile.TemporaryDirectory() as tmp:
            store = MetricsStore(Path(tmp) / "metrics.db")
            for key in banned:
                with self.subTest(key=key):
                    with self.assertRaises(ValueError):
                        store.record({"decision": "bypass", key: "SECRET_SENTINEL"})
            self.assertEqual(store.summary()["requests"], 0)
            self.assertNotIn(b"SECRET_SENTINEL", (Path(tmp) / "metrics.db").read_bytes())

    def test_metrics_database_is_private_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions only")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.db"
            MetricsStore(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
