from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse


_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}
_ALLOWED_KEYS = {"upstream", "host", "port", "state_dir"}


@dataclass(frozen=True, slots=True)
class TokenConfig:
    upstream: str
    host: str = "127.0.0.1"
    port: int = 8788
    state_dir: str = ""

    def __post_init__(self) -> None:
        parsed = urlparse(self.upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("upstream must be an http(s) URL")
        if self.host not in _ALLOWED_HOSTS:
            raise ValueError("V1 gateway bind must be loopback")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("port must be in 1..65535")
        if not self.state_dir:
            raise ValueError("state_dir is required")

def default_config_path(home: str | Path | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / ".config" / "token" / "config.json"


def default_state_dir(home: str | Path | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / ".local" / "state" / "token"


def load_config(path: str | Path) -> TokenConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"unknown config fields: {sorted(unknown)}")
    missing = _ALLOWED_KEYS - set(data)
    if missing:
        raise ValueError(f"missing config fields: {sorted(missing)}")
    return TokenConfig(**data)


def save_config(config: TokenConfig, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(asdict(config), indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".token-config-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
        if os.name == "posix":
            os.chmod(target, 0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
