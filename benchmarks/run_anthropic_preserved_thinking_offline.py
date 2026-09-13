from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import tempfile
from pathlib import Path
from typing import Any

from token_runtime.anthropic_adapter import AnthropicMessagesAdapter
from token_runtime.anthropic_preserved_thinking_cert import (
    MODEL_ID,
    AnthropicPreservedThinkingOfflineEvidence,
    classify_anthropic_preserved_thinking,
)
from token_runtime.engine import OptimizationEngine
from token_runtime.model import OptimizationDecision, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


REQUIRED_INVENTORY = {
    "cache_control",
    "redacted_thinking",
    "thinking",
    "tool_result",
    "tool_use",
}
EVIDENCE_ID = "token-anthropic-preserved-thinking-cert-1:offline-v1"


def _load(corpus: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], dict[str, Any]]]]:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in manifest["trajectories"]:
        payload = json.loads((corpus / item["file"]).read_text(encoding="utf-8"))
        cases.append((item, payload))
    return manifest, cases


def _has_protocol_state(envelope: RequestEnvelope) -> bool:
    return any(block.kind == "protocol_state" for block in envelope.blocks)


def _protected_prefix_exact(
    envelope: RequestEnvelope,
    original: dict[str, Any],
    token_on: dict[str, Any],
    decision: OptimizationDecision,
    reasons: tuple[str, ...],
) -> bool:
    return (
        _has_protocol_state(envelope)
        and not envelope.wire_safe
        and decision is OptimizationDecision.BYPASS
        and "unsupported_wire_shape" in reasons
        and token_on == original
    )


def _inventory_markers(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        part_type = value.get("type")
        if part_type in {"thinking", "redacted_thinking", "tool_use", "tool_result"}:
            found.add(part_type)
        if "cache_control" in value:
            found.add("cache_control")
        for child in value.values():
            found.update(_inventory_markers(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_inventory_markers(child))
    return found


def _tool_links(payload: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    uses: list[str] = []
    results: list[str] = []
    for message in payload.get("messages", []):
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and isinstance(part.get("id"), str):
                uses.append(part["id"])
            if part.get("type") == "tool_result" and isinstance(part.get("tool_use_id"), str):
                results.append(part["tool_use_id"])
    return tuple(uses), tuple(results)


def _cache_markers(value: Any) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        if "cache_control" in value:
            found.append(json.dumps(value["cache_control"], sort_keys=True, separators=(",", ":")))
        for child in value.values():
            found.extend(_cache_markers(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_cache_markers(child))
    return tuple(found)


def _strip_reasoning_blocks(payload: dict[str, Any]) -> dict[str, Any]:
    control = deepcopy(payload)
    for message in control.get("messages", []):
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        message["content"] = [
            part
            for part in message["content"]
            if not (isinstance(part, dict) and part.get("type") in {"thinking", "redacted_thinking"})
        ]
    return control


def build_payload(corpus: Path) -> dict[str, object]:
    manifest, cases = _load(corpus)
    adapter = AnthropicMessagesAdapter()
    protected_checks: list[bool] = []
    off_on_checks: list[bool] = []
    tool_checks: list[bool] = []
    cache_checks: list[bool] = []
    resume_checks: list[bool] = []
    unknown_checks: list[bool] = []
    reducible_controls: list[bool] = []
    optimized_count = 0
    bypass_count = 0
    changed_ids: set[str] = set()
    bypass_reasons: Counter[str] = Counter()
    observed_inventory: set[str] = set()
    model_checks: list[bool] = []

    with tempfile.TemporaryDirectory() as tmp:
        engine = OptimizationEngine(
            planner=ContextPlanner(),
            store=RecoveryStore(Path(tmp) / "recovery.db"),
        )
        for item, original in cases:
            observed_inventory.update(_inventory_markers(original))
            model_checks.append(original.get("model") == MODEL_ID)
            envelope = adapter.parse(original)
            result = engine.optimize(envelope)
            token_on = adapter.serialize(result.envelope)
            checks = set(item["checks"])

            expected = OptimizationDecision(item["expected_decision"].lower())
            if result.decision is not expected:
                raise AssertionError(f"{item['id']} decision drifted: {result.decision.value}")
            if result.decision is OptimizationDecision.OPTIMIZE:
                optimized_count += 1
            else:
                bypass_count += 1
                bypass_reasons.update(result.reasons)
            changed_ids.update(result.changed_block_ids)

            if "protected_prefix" in checks:
                protected_checks.append(
                    _protected_prefix_exact(
                        envelope, original, token_on, result.decision, result.reasons
                    )
                )
            if "off_on" in checks:
                off_on_checks.append(token_on == original)
            if "tool_history" in checks:
                original_uses, original_results = _tool_links(original)
                token_uses, token_results = _tool_links(token_on)
                tool_checks.append(
                    bool(original_uses)
                    and bool(original_results)
                    and original_uses == original_results
                    and (token_uses, token_results) == (original_uses, original_results)
                    and token_on.get("messages") == original.get("messages")
                )
            if "cache" in checks:
                cache_checks.append(
                    _cache_markers(token_on) == _cache_markers(original)
                    and bool(_cache_markers(original))
                )
            if "resume" in checks:
                resume_checks.append(
                    token_on == original
                    and _has_protocol_state(envelope)
                    and result.decision is OptimizationDecision.BYPASS
                )
            if "unknown_passthrough" in checks:
                unknown_checks.append(
                    not envelope.wire_safe
                    and result.decision is OptimizationDecision.BYPASS
                    and token_on == original
                )
            if "reducible_control" in checks:
                control = _strip_reasoning_blocks(original)
                control_envelope = adapter.parse(control)
                control_result = engine.optimize(control_envelope)
                reducible_controls.append(
                    control_envelope.wire_safe
                    and control_result.decision is OptimizationDecision.OPTIMIZE
                    and bool(control_result.changed_block_ids)
                )

    declared_inventory = set(manifest.get("inventory", ()))
    inventory_complete = (
        observed_inventory == REQUIRED_INVENTORY
        and declared_inventory == REQUIRED_INVENTORY
    )
    model_scope_exact = bool(model_checks) and all(model_checks)
    hard_bypass_complete = (
        len(cases) == 5
        and bypass_count == 5
        and optimized_count == 0
        and not changed_ids
        and bypass_reasons == Counter({"unsupported_wire_shape": 5})
    )
    protected_prefix_exact = bool(protected_checks) and all(protected_checks)
    token_off_on_wire_equivalent = bool(off_on_checks) and all(off_on_checks)
    tool_history_fidelity = bool(tool_checks) and all(tool_checks)
    cache_metadata_preserved = bool(cache_checks) and all(cache_checks)
    resume_continuity = bool(resume_checks) and all(resume_checks)
    unknown_native_passthrough = bool(unknown_checks) and all(unknown_checks)
    thinking_stripped_control_reducible = bool(reducible_controls) and all(reducible_controls)

    offline = AnthropicPreservedThinkingOfflineEvidence(
        evidence_id=EVIDENCE_ID,
        inventory_complete=inventory_complete,
        model_scope_exact=model_scope_exact,
        hard_bypass_complete=hard_bypass_complete,
        thinking_stripped_control_reducible=thinking_stripped_control_reducible,
        protected_prefix_exact=protected_prefix_exact,
        token_off_on_wire_equivalent=token_off_on_wire_equivalent,
        tool_history_fidelity=tool_history_fidelity,
        cache_metadata_preserved=cache_metadata_preserved,
        resume_continuity=resume_continuity,
        unknown_native_passthrough=unknown_native_passthrough,
    )
    record = classify_anthropic_preserved_thinking(offline, None)
    return {
        "bypass_count": bypass_count,
        "bypass_reasons": dict(sorted(bypass_reasons.items())),
        "cache_metadata_preserved": cache_metadata_preserved,
        "changed_block_ids": sorted(changed_ids),
        "classification": record.state.value,
        "classification_reason": record.reason,
        "corpus_cases": len(cases),
        "evidence_id": offline.evidence_id,
        "generation_id": manifest["generation_id"],
        "inventory_complete": inventory_complete,
        "model_scope_exact": model_scope_exact,
        "hard_bypass_complete": hard_bypass_complete,
        "optimized_count": optimized_count,
        "protected_prefix_exact": protected_prefix_exact,
        "resume_continuity": resume_continuity,
        "thinking_stripped_control_reducible": thinking_stripped_control_reducible,
        "token_off_on_wire_equivalent": token_off_on_wire_equivalent,
        "tool_history_fidelity": tool_history_fidelity,
        "unknown_native_passthrough": unknown_native_passthrough,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    payload = build_payload(args.corpus)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
