from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re

from .model import ContextBlock
from .store import RecoveryStore


_ANCHOR_RE = re.compile(
    r"\b(error|failed|failure|exception|warning|must|never|constraint|decision|status|exit code)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Reduction:
    block: ContextBlock
    changed: bool
    reducer_id: str | None = None
    recovery_ref: str | None = None


def _unchanged(block: ContextBlock) -> Reduction:
    return Reduction(block=block, changed=False)


def _is_json_container(text: str) -> bool:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(value, (dict, list))


class RepeatedLineReducer:
    reducer_id = "repeat_runs_v1"

    def reduce(self, block: ContextBlock, store: RecoveryStore, *, protected: bool) -> Reduction:
        if protected or _is_json_container(block.text):
            return _unchanged(block)
        lines = block.text.splitlines()
        if len(lines) < 2:
            return _unchanged(block)

        out: list[str] = []
        current = lines[0]
        count = 1
        for line in lines[1:]:
            if line == current:
                count += 1
                continue
            out.append(current if count == 1 else f"{current}  [repeated x{count}]")
            current, count = line, 1
        out.append(current if count == 1 else f"{current}  [repeated x{count}]")
        candidate = "\n".join(out)
        if candidate == block.text or len(candidate) >= len(block.text):
            return _unchanged(block)
        ref = store.put(block.text.encode())
        return Reduction(
            block=replace(block, text=candidate),
            changed=True,
            reducer_id=self.reducer_id,
            recovery_ref=ref,
        )


class JsonToolOutputReducer:
    reducer_id = "json_minify_v1"

    def reduce(self, block: ContextBlock, store: RecoveryStore, *, protected: bool) -> Reduction:
        if protected or block.kind != "tool_output" or not _is_json_container(block.text):
            return _unchanged(block)
        value = json.loads(block.text)
        candidate = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(candidate) >= len(block.text):
            return _unchanged(block)
        ref = store.put(block.text.encode())
        return Reduction(block=replace(block, text=candidate), changed=True,
                         reducer_id=self.reducer_id, recovery_ref=ref)


class ToolOutputReducer:
    reducer_id = "tool_output_v1"

    def __init__(self, min_chars: int = 1800, edge_lines: int = 8):
        self.min_chars = min_chars
        self.edge_lines = edge_lines

    def reduce(self, block: ContextBlock, store: RecoveryStore, *, protected: bool) -> Reduction:
        if (protected or block.kind != "tool_output" or len(block.text) < self.min_chars
                or _is_json_container(block.text)):
            return _unchanged(block)

        lines = block.text.splitlines()
        edge = self.edge_lines
        if len(lines) <= edge * 2 + 1:
            return _unchanged(block)
        middle = lines[edge:-edge]
        anchors = [line for line in middle if _ANCHOR_RE.search(line)]
        ref = store.put(block.text.encode())
        marker = f"[TOKEN_REF:{ref}]"
        candidate_lines = lines[:edge] + anchors + [marker] + lines[-edge:]
        candidate = "\n".join(dict.fromkeys(candidate_lines))
        if len(candidate) >= len(block.text):
            return _unchanged(block)
        return Reduction(
            block=replace(block, text=candidate),
            changed=True,
            reducer_id=self.reducer_id,
            recovery_ref=ref,
        )


_EXPLICIT_GUARD_RE = re.compile(
    r"(?im)^\s*DECISION\s*:|\b(must|never|do not|don't|required|constraint)\b"
)


class RetrievedDuplicateReducer:
    """Remove long exact adjacent duplicate spans from old retrieval/tool evidence."""

    reducer_id = "evidence_exact_duplicate_v1"

    def __init__(self, min_words: int = 8):
        self.min_words = min_words

    def reduce(self, block: ContextBlock, store: RecoveryStore, *, protected: bool) -> Reduction:
        if (protected or block.kind not in {"retrieved", "tool_output"}
                or _EXPLICIT_GUARD_RE.search(block.text) or _is_json_container(block.text)):
            return _unchanged(block)
        candidate = self._collapse_text(block.text)
        if candidate == block.text or len(candidate) >= len(block.text):
            return _unchanged(block)
        ref = store.put(block.text.encode())
        return Reduction(
            block=replace(block, text=candidate),
            changed=True,
            reducer_id=self.reducer_id,
            recovery_ref=ref,
        )

    def _collapse_text(self, text: str) -> str:
        lines = text.splitlines(keepends=True)
        return "".join(self._collapse_line(line) for line in lines)

    def _collapse_line(self, line: str) -> str:
        newline = ""
        body = line
        if body.endswith("\r\n"):
            body, newline = body[:-2], "\r\n"
        elif body.endswith("\n"):
            body, newline = body[:-1], "\n"

        while True:
            match = self._longest_adjacent_repeat(body)
            if match is None:
                return body + newline
            start_second, end_second = match
            left = body[:start_second].rstrip()
            right = body[end_second:]
            body = left + right

    def _longest_adjacent_repeat(self, text: str) -> tuple[int, int] | None:
        words = list(re.finditer(r"\S+", text))
        tokens = [item.group(0) for item in words]
        best: tuple[int, int, int] | None = None
        for start in range(len(tokens)):
            max_span = (len(tokens) - start) // 2
            for span in range(max_span, self.min_words - 1, -1):
                if tokens[start:start + span] != tokens[start + span:start + 2 * span]:
                    continue
                second_start = words[start + span].start()
                second_end = words[start + 2 * span - 1].end()
                if best is None or span > best[0]:
                    best = (span, second_start, second_end)
                break
        return None if best is None else (best[1], best[2])
