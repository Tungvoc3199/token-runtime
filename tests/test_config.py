import os
import stat
import tempfile
import unittest
from pathlib import Path

from token_runtime.config import TokenConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_save_and_load_round_trip_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = TokenConfig(
                upstream="http://127.0.0.1:20128",
                host="127.0.0.1",
                port=8788,
                state_dir=str(Path(tmp) / "state"),
            )
            save_config(config, path)
            self.assertEqual(load_config(path), config)
            if os.name == "posix":
                mode = stat.S_IMODE(path.stat().st_mode)
                self.assertEqual(mode, 0o600)

    def test_rejects_non_loopback_bind_by_default(self):
        with self.assertRaises(ValueError):
            TokenConfig(
                upstream="https://api.example.test",
                host="0.0.0.0", port=8788, state_dir="/tmp/token",
            )

    def test_rejects_non_http_upstream(self):
        with self.assertRaises(ValueError):
            TokenConfig(
                upstream="file:///tmp/socket",
                host="127.0.0.1", port=8788, state_dir="/tmp/token",
            )

    def test_load_rejects_unknown_config_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                '{"upstream":"http://127.0.0.1:1","host":"127.0.0.1",'
                '"port":8788,"state_dir":"/tmp/x","secret":"no"}'
            )
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
