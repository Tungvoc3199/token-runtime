from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
import os
from pathlib import Path
import re
import shutil
import tomllib

_CYAN = "\x1b[38;2;34;211;238m"
_SLATE = "\x1b[38;2;122;135;147m"
_BOLD = "\x1b[1m"
_RESET = "\x1b[0m"


def _display_version(raw: str) -> str:
    alpha = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", raw)
    if alpha:
        return f"v{alpha.group(1)}-alpha.{alpha.group(2)}"
    return raw if raw.startswith("v") else f"v{raw}"


def _runtime_version() -> str:
    try:
        return package_version("token-runtime")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
        except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
            return "dev"


def _supports_color(stdout, env: dict[str, str]) -> bool:
    if "NO_COLOR" in env or env.get("TERM") == "dumb":
        return False
    return bool(getattr(stdout, "isatty", lambda: False)())


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def _full_lines(version: str, color: bool) -> list[str]:
    cyan = lambda text: _paint(text, _CYAN, color)
    bold = lambda text: _paint(text, _BOLD, color)
    slate = lambda text: _paint(text, _SLATE, color)
    return [
        "",
        f"  {cyan('▰   ▰')}       ╲",
        f"    {cyan('▰')}          ╲╲       {cyan('┃▶')}    {bold('TOKEN')}",
        f"  {cyan('▰   ▰')}       ╱              {slate('Adaptive Context Runtime')}",
        "",
        f"  {cyan(version)}  ·  Local-first  ·  Safety-first",
        "",
        f"  {bold('Quick start')}",
        "    token doctor      Check runtime health",
        "    token status      Show optimization metrics",
        "    token serve       Start local gateway",
        "    token benchmark   Run evaluation",
        "",
        "  " + slate("Reduce context when safe. Pass through when it isn't."),
        "",
    ]


def _compact_lines(version: str, color: bool) -> list[str]:
    cyan = lambda text: _paint(text, _CYAN, color)
    bold = lambda text: _paint(text, _BOLD, color)
    slate = lambda text: _paint(text, _SLATE, color)
    return [
        "",
        f"  {cyan('▰ ▰')}  ╲",
        f"   {cyan('▰')}   ╲╲ {cyan('┃▶')} {bold('TOKEN')}",
        f"  {cyan('▰ ▰')}  ╱   {slate('Adaptive Context Runtime')}",
        "",
        f"  {cyan(version)} · Local-first · Safety-first",
        "",
        "  token doctor   Check health",
        "  token status   Show metrics",
        "",
        "  Reduce context when safe.",
        "  Pass through when it isn't.",
        "",
    ]


def render_welcome(stdout, *, version: str | None = None, width: int | None = None,
                   color: bool | None = None, env: dict[str, str] | None = None) -> None:
    env = dict(os.environ) if env is None else env
    width = width or shutil.get_terminal_size((80, 24)).columns
    enabled = _supports_color(stdout, env) if color is None else color
    display_version = _display_version(version or _runtime_version())
    lines = _compact_lines(display_version, enabled) if width < 64 else _full_lines(display_version, enabled)
    stdout.write("\n".join(lines))
