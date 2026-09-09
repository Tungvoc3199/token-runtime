from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .model import OptimizationDecision, RequestEnvelope


_DECISION_RE = re.compile(r"(?im)^\s*DECISION\s*:\s*(.+?)\s*$")
_CONSTRAINT_RE = re.compile(r"\b(must|never|do not|don't|constraint|required)\b", re.I)
_EXACT_EDIT_MARKERS = ("old_string=", "new_string=", "diff --git", "*** Begin Patch")
_PROTOCOL_KINDS = {
    "system", "developer", "tools", "tool_schema", "tool_call", "function_call"
}


def _is_structured_json(text: str) -> bool:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(value, (dict, list))


@dataclass(frozen=True, slots=True)
class Plan:
    decision: OptimizationDecision
    protected_ids: frozenset[str]
    reasons: tuple[str, ...]


class ContextPlanner:
    def plan(self, envelope: RequestEnvelope) -> Plan:
        protected: set[str] = set()
        reasons: list[str] = []
        latest_turn = max((block.turn_index for block in envelope.blocks), default=0)

        for block in envelope.blocks:
            if block.kind in _PROTOCOL_KINDS:
                protected.add(block.id)
            if _CONSTRAINT_RE.search(block.text):
                protected.add(block.id)
            if block.turn_index == latest_turn:
                protected.add(block.id)

        self._protect_latest(envelope, "user", protected)
        self._protect_latest(envelope, "tool_output", protected)

        active_decisions: list[str] = []
        for block in envelope.blocks:
            matches = _DECISION_RE.findall(block.text)
            if matches:
                protected.add(block.id)
            if block.turn_index != latest_turn or block.kind in _PROTOCOL_KINDS:
                continue
            for match in matches:
                active_decisions.append(" ".join(match.lower().split()))

        if not envelope.wire_safe:
            reasons.append("unsupported_wire_shape")
        if any(
            marker in block.text
            for block in envelope.blocks
            for marker in _EXACT_EDIT_MARKERS
        ):
            reasons.append("exact_edit_context")
        if len(set(active_decisions)) > 1:
            reasons.append("competing_active_decisions")
        has_decision_context = any(_DECISION_RE.search(block.text) for block in envelope.blocks)
        has_structured_evidence = any(
            block.kind == "tool_output" and _is_structured_json(block.text)
            for block in envelope.blocks
        )
        if has_decision_context and has_structured_evidence:
            reasons.append("structured_decision_context")

        if reasons:
            return Plan(OptimizationDecision.BYPASS, frozenset(protected), tuple(reasons))
        return Plan(
            OptimizationDecision.OPTIMIZE,
            frozenset(protected),
            ("eligible_request",),
        )

    @staticmethod
    def _protect_latest(
        envelope: RequestEnvelope, kind: str, protected: set[str]
    ) -> None:
        candidates = [
            (block.turn_index, index, block.id)
            for index, block in enumerate(envelope.blocks)
            if block.kind == kind
        ]
        if candidates:
            protected.add(max(candidates)[2])
