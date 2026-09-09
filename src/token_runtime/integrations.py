from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Literal


_BEGIN = b"# >>> TOKEN MANAGED >>>"
_END = b"# <<< TOKEN MANAGED <<<"
_BASE_RE = re.compile(br"(?m)^OPENAI_BASE_URL\s*=.*$")
_MANAGED_RE = re.compile(
    re.escape(_BEGIN) + br"\r?\n.*?\r?\n" + re.escape(_END) + br"(?:\r?\n)?",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Integration:
    kind: Literal["codex", "openai_env"]
    path: Path
    root: Path


@dataclass(frozen=True, slots=True)
class InstallPlan:
    integration: Integration
    mode: Literal["sidecar", "managed_block", "managed_toml"]
    target_path: Path
    gateway_url: str
    original_bytes: bytes | None
    desired_bytes: bytes
    safe_to_apply: bool = True
    reason: str = "ready"
    metadata_path: Path | None = None
    metadata_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class ApplyResult:
    changed: bool
    reason: str
    target_path: Path


def detect_integrations(root: str | Path) -> list[Integration]:
    base = Path(root)
    found: list[Integration] = []
    codex = base / ".codex" / "config.toml"
    if codex.is_file():
        found.append(Integration("codex", codex, base))
    env = base / ".env"
    if env.is_file():
        content = env.read_bytes()
        if b"OPENAI_" in content or _BEGIN in content:
            found.append(Integration("openai_env", env, base))
    return found


def _managed_block(gateway_url: str) -> bytes:
    return (
        _BEGIN + b"\n" +
        f"OPENAI_BASE_URL={gateway_url}\n".encode("utf-8") +
        _END + b"\n"
    )


def _replace_or_append_block(original: bytes, gateway_url: str) -> bytes:
    block = _managed_block(gateway_url)
    if _MANAGED_RE.search(original):
        return _MANAGED_RE.sub(block, original, count=1)
    separator = b"" if not original or original.endswith((b"\n", b"\r")) else b"\n"
    return original + separator + block


def _codex_provider_sections(content: bytes):
    return list(re.finditer(br"(?m)^\[model_providers\.([A-Za-z0-9_-]+)\][ \t]*(?:\r?\n|$)", content))


def _replace_codex_base_url(content: bytes, provider_id: str, new_url: str):
    sections = _codex_provider_sections(content)
    match = next((m for m in sections if m.group(1).decode() == provider_id), None)
    if match is None:
        return None
    next_headers = [m.start() for m in re.finditer(br"(?m)^\[[^\r\n]+\][ \t]*(?:\r?\n|$)", content) if m.start() > match.start()]
    end = min(next_headers) if next_headers else len(content)
    section = content[match.end():end]
    base = re.search(br'(?m)^[ \t]*base_url[ \t]*=[ \t]*"([^"\r\n]+)"', section)
    if base is None:
        return None
    start = match.end() + base.start(1)
    stop = match.end() + base.end(1)
    old = content[start:stop].decode("utf-8")
    desired = content[:start] + new_url.encode("utf-8") + content[stop:]
    return old, desired


def _plan_codex(integration: Integration, gateway_url: str) -> InstallPlan:
    original = integration.path.read_bytes()
    target = integration.path
    metadata_path = integration.root / ".token" / "integrations" / "codex.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return InstallPlan(integration, "managed_toml", target, gateway_url, original, original, False, "invalid_codex_metadata", metadata_path)
        current_hash = hashlib.sha256(original).hexdigest()
        if metadata.get("strategy") == "managed_provider_base_url" and current_hash == metadata.get("desired_sha256"):
            return InstallPlan(integration, "managed_toml", target, gateway_url, original, original, True, "already_managed", metadata_path, metadata_path.read_bytes())
        return InstallPlan(integration, "managed_toml", target, gateway_url, original, original, False, "target_drift", metadata_path)
    sections = _codex_provider_sections(original)
    if len(sections) != 1:
        reason = "ambiguous_codex_provider" if len(sections) > 1 else "missing_codex_provider"
        return InstallPlan(integration, "managed_toml", target, gateway_url, original, original, False, reason, metadata_path)
    provider_id = sections[0].group(1).decode("utf-8")
    replaced = _replace_codex_base_url(original, provider_id, gateway_url)
    if replaced is None:
        return InstallPlan(integration, "managed_toml", target, gateway_url, original, original, False, "missing_codex_base_url", metadata_path)
    old_url, desired = replaced
    metadata = {
        "kind": "codex", "strategy": "managed_provider_base_url",
        "provider_id": provider_id, "gateway_url": gateway_url,
        "original_base_url": old_url,
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "desired_sha256": hashlib.sha256(desired).hexdigest(),
    }
    metadata_bytes = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return InstallPlan(integration, "managed_toml", target, gateway_url, original, desired, True, "ready", metadata_path, metadata_bytes)


def plan_install(integration: Integration, *, gateway_url: str) -> InstallPlan:
    if integration.kind == "codex":
        return _plan_codex(integration, gateway_url)

    original = integration.path.read_bytes()
    unmanaged = _BASE_RE.search(_MANAGED_RE.sub(b"", original))
    safe = unmanaged is None
    desired = _replace_or_append_block(original, gateway_url) if safe else original
    metadata_path = integration.root / ".token" / "integrations" / "openai_env.json"
    if metadata_path.exists():
        metadata_bytes = metadata_path.read_bytes()
    else:
        separator_added = bool(original and not original.endswith((b"\n", b"\r")))
        metadata_bytes = (json.dumps({
            "kind": "openai_env",
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "separator_added": separator_added,
        }, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return InstallPlan(
        integration, "managed_block", integration.path, gateway_url,
        original, desired, safe_to_apply=safe,
        reason="ready" if safe else "existing_openai_base_url_unmanaged",
        metadata_path=metadata_path, metadata_bytes=metadata_bytes,
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".token-tmp")
    tmp.write_bytes(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def apply_plan(plan: InstallPlan, *, apply: bool = False) -> ApplyResult:
    current = plan.target_path.read_bytes() if plan.target_path.exists() else None
    changed = current != plan.desired_bytes
    if not plan.safe_to_apply:
        return ApplyResult(False, plan.reason, plan.target_path)
    if not apply or not changed:
        return ApplyResult(changed, "dry_run" if not apply else "unchanged", plan.target_path)
    if current not in (plan.original_bytes, plan.desired_bytes):
        return ApplyResult(False, "target_drift", plan.target_path)
    try:
        _atomic_write(plan.target_path, plan.desired_bytes)
        if plan.metadata_path is not None and plan.metadata_bytes is not None:
            _atomic_write(plan.metadata_path, plan.metadata_bytes)
    except Exception:
        if plan.original_bytes is None:
            plan.target_path.unlink(missing_ok=True)
        else:
            _atomic_write(plan.target_path, plan.original_bytes)
        if plan.metadata_path is not None:
            plan.metadata_path.unlink(missing_ok=True)
        raise
    return ApplyResult(True, "applied", plan.target_path)


def restore_plan(plan: InstallPlan, *, apply: bool = False) -> ApplyResult:
    current = plan.target_path.read_bytes() if plan.target_path.exists() else None
    desired = plan.original_bytes
    metadata_exists = bool(plan.metadata_path and plan.metadata_path.exists())
    changed = current != desired or metadata_exists
    if not apply or not changed:
        return ApplyResult(changed, "dry_run" if not apply else "unchanged", plan.target_path)
    if current not in (plan.original_bytes, plan.desired_bytes):
        return ApplyResult(False, "target_drift", plan.target_path)
    if current != desired:
        if desired is None:
            plan.target_path.unlink(missing_ok=True)
        else:
            _atomic_write(plan.target_path, desired)
    if plan.metadata_path is not None:
        plan.metadata_path.unlink(missing_ok=True)
    return ApplyResult(True, "restored", plan.target_path)


def uninstall_integration(integration: Integration, *, apply: bool = False) -> ApplyResult:
    if integration.kind == "codex":
        metadata_path = integration.root / ".token" / "integrations" / "codex.json"
        if not metadata_path.exists():
            return ApplyResult(False, "unchanged" if apply else "dry_run", integration.path)
        if not apply:
            return ApplyResult(True, "dry_run", integration.path)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return ApplyResult(False, "invalid_codex_metadata", integration.path)
        if metadata.get("strategy") == "sidecar":
            metadata_path.unlink()
            return ApplyResult(True, "uninstalled", integration.path)
        if metadata.get("strategy") != "managed_provider_base_url":
            return ApplyResult(False, "invalid_codex_metadata", integration.path)
        current = integration.path.read_bytes()
        current_hash = hashlib.sha256(current).hexdigest()
        if current_hash == metadata.get("original_sha256"):
            metadata_path.unlink()
            return ApplyResult(True, "metadata_removed", integration.path)
        if current_hash != metadata.get("desired_sha256"):
            return ApplyResult(False, "target_drift", integration.path)
        restored = _replace_codex_base_url(current, str(metadata.get("provider_id")), str(metadata.get("original_base_url")))
        if restored is None:
            return ApplyResult(False, "restore_failed", integration.path)
        _, desired = restored
        if hashlib.sha256(desired).hexdigest() != metadata.get("original_sha256"):
            return ApplyResult(False, "restore_hash_mismatch", integration.path)
        _atomic_write(integration.path, desired)
        metadata_path.unlink()
        return ApplyResult(True, "uninstalled", integration.path)

    target = integration.path
    current = target.read_bytes()
    match = _MANAGED_RE.search(current)
    metadata_path = integration.root / ".token" / "integrations" / "openai_env.json"
    metadata_exists = metadata_path.exists()
    if match is None:
        if apply and metadata_exists:
            metadata_path.unlink()
        changed = metadata_exists
        return ApplyResult(changed, "metadata_removed" if apply and changed else ("dry_run" if not apply else "unchanged"), target)

    separator_added = False
    if metadata_exists:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            separator_added = bool(metadata.get("separator_added", False))
        except (OSError, ValueError, TypeError):
            separator_added = False
    start = match.start()
    end = match.end()
    desired = current[:start] + current[end:]
    if separator_added and start > 0 and current[start - 1:start] == b"\n":
        desired = current[:start - 1] + current[end:]

    if not apply:
        return ApplyResult(True, "dry_run", target)
    _atomic_write(target, desired)
    metadata_path.unlink(missing_ok=True)
    return ApplyResult(True, "uninstalled", target)
