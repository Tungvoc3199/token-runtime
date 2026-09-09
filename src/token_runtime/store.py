from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3


class RecoveryStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS recovery ("
                "ref TEXT PRIMARY KEY, payload BLOB NOT NULL)"
            )
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def put(self, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        ref = f"sha256:{digest}"
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO recovery(ref, payload) VALUES(?, ?)",
                (ref, sqlite3.Binary(payload)),
            )
        return ref

    def get(self, ref: str) -> bytes:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM recovery WHERE ref = ?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        return bytes(row[0])
