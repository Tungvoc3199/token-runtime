from __future__ import annotations

import argparse
import re
from pathlib import Path


_RULES = (
    ("private-key-header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("openai-token", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("posix-home-path", re.compile(r"/home/[A-Za-z0-9._-]+/")),
    ("windows-home-path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\", re.I)),
    (
        "private-repo-url",
        re.compile(r"https?://github\.com/Tungvoc3199/token(?:[/?#]|$)", re.I),
    ),
)

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_INTERNAL_TERMS = (
    "TH" + "ADC",
    "AI" + "OS",
    "9" + "Router",
    "Open" + "Claw",
    "anh" + "-duong",
    "Visual" + "Forge",
)


def _text_findings(relative: str, text: str) -> list[str]:
    findings: list[str] = []
    haystack = relative + "\n" + text
    for rule_id, pattern in _RULES:
        if pattern.search(haystack):
            findings.append(f"{relative}: {rule_id}")
    for match in _EMAIL.finditer(haystack):
        address = match.group(0).lower()
        if "noreply" not in address:
            findings.append(f"{relative}: raw-email")
            break
    lowered = haystack.lower()
    for term in _INTERNAL_TERMS:
        if term.lower() in lowered:
            findings.append(f"{relative}: internal-name:{term}")
    return findings


def audit_public_paths(root: Path, relative_paths: list[str]) -> list[str]:
    root = Path(root)
    findings: list[str] = []
    for relative in sorted(relative_paths):
        path = root / relative
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: binary-file")
            continue
        findings.extend(_text_findings(relative, text))
    return findings


def audit_public_tree(root: Path) -> list[str]:
    root = Path(root)
    paths = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return audit_public_paths(root, paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=None)
    parser.add_argument("--source-tree", type=Path, default=None)
    args = parser.parse_args()
    if args.source_tree is not None:
        if __package__:
            from .public_release import classify_files
        else:
            from public_release import classify_files
        public_files, _ = classify_files(args.source_tree)
        findings = audit_public_paths(args.source_tree, public_files)
    else:
        findings = audit_public_tree(args.root or Path("."))
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
