from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

if __package__:
    from .public_audit import audit_public_tree
else:
    from public_audit import audit_public_tree


def tree_digest(root: Path) -> str:
    root = Path(root)
    digest = hashlib.sha256()
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.relative_to(root).parts
        and p.suffix not in {".pyc", ".pyo"}
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _listed_files(source: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    return sorted({item.decode("utf-8") for item in result.stdout.split(b"\0") if item})


def _patterns(source: Path) -> tuple[list[str], list[str]]:
    data = tomllib.loads((source / "public-release.toml").read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported public-release schema")
    files = data["files"]
    return list(files["public"]), list(files["private"])


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_files(source: Path) -> tuple[list[str], list[str]]:
    public_patterns, private_patterns = _patterns(source)
    public: list[str] = []
    private: list[str] = []
    for path in _listed_files(source):
        is_public = _matches(path, public_patterns)
        is_private = _matches(path, private_patterns)
        if is_public and is_private:
            raise ValueError(f"ambiguous classification: {path}")
        if not is_public and not is_private:
            raise ValueError(f"unclassified file: {path}")
        (public if is_public else private).append(path)
    return public, private


def source_is_clean(source: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    return not result.stdout.strip()


def _copy_public_files(source: Path, destination: Path, public_files: list[str]) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in public_files:
        src = source / relative
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def build_public_release(source: Path, destination: Path, version: str) -> dict[str, object]:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    public_files, _ = classify_files(source)
    _copy_public_files(source, destination, public_files)

    findings = audit_public_tree(destination)
    if findings:
        raise ValueError("public audit failed:\n" + "\n".join(findings))

    runtime_digest = tree_digest(source / "src" / "token_runtime")
    exported_runtime_digest = tree_digest(destination / "src" / "token_runtime")
    if runtime_digest != exported_runtime_digest:
        raise ValueError("runtime tree digest mismatch")

    manifest: dict[str, object] = {
        "schema_version": 1,
        "release_version": version,
        "runtime_tree_sha256": runtime_digest,
        "public_payload_sha256": tree_digest(destination),
        "file_count": len(public_files),
    }
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (destination / "PUBLIC_RELEASE_MANIFEST.json").write_text(rendered, encoding="utf-8")

    final_findings = audit_public_tree(destination)
    if final_findings:
        raise ValueError("public audit failed after manifest:\n" + "\n".join(final_findings))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    if args.require_clean and not source_is_clean(args.source):
        raise SystemExit("source tree is dirty; release build requires a clean source")
    manifest = build_public_release(args.source, args.destination, args.version)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
