import os
import stat
import tempfile
import unittest
from pathlib import Path

from token_runtime.store import RecoveryStore


class RecoveryStoreTests(unittest.TestCase):
    def test_round_trip_preserves_non_utf8_bytes_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            raw = b"prefix\x00\xff\x80suffix\n"
            ref = store.put(raw)
            self.assertEqual(store.get(ref), raw)

    def test_same_bytes_have_stable_content_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            first = store.put(b"same")
            second = store.put(b"same")
            self.assertEqual(first, second)

    def test_recovery_database_is_private_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions only")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recovery.db"
            RecoveryStore(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
