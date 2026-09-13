from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from .capabilities import CapabilityKey
from .compat_cert import BenchmarkGeneration
from .compatibility import CompatibilityRecord, CompatibilityState


MODEL_ID = "claude-fable-5-1"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
BINDING_MODE = "drop_block"
GENERATION_ID = "token-anthropic-preserved-thinking-cert-1:pt-v1"
CORPUS_VERSION = "anthropic-preserved-thinking-v1"
EVALUATOR_VERSION = "anthropic-pt-eval-v2"
POLICY_VERSION = "compat-policy-v1"
ACCOUNTING_STATES = frozenset({
    "unavailable",
    "estimated_from_response_usage",
    "usage_reconciled",
    "billed_workspace_delta_reconciled",
})

ANTHROPIC_PRESERVED_THINKING_KEY = CapabilityKey(
    "generic-anthropic", "anthropic_messages", "anthropic", model_family=MODEL_ID
)


def _require_evidence_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("evidence_id must be non-blank")


def _require_bool_fields(instance: object, names: tuple[str, ...]) -> None:
    values = {item.name: getattr(instance, item.name) for item in fields(instance)}
    for name in names:
        if type(values[name]) is not bool:
            raise TypeError(f"{name} must be bool")


def _require_nonnegative_finite_decimal(value: str, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal string") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


@dataclass(frozen=True, slots=True)
class AnthropicPreservedThinkingOfflineEvidence:
    evidence_id: str
    inventory_complete: bool
    model_scope_exact: bool
    hard_bypass_complete: bool
    thinking_stripped_control_reducible: bool
    protected_prefix_exact: bool
    token_off_on_wire_equivalent: bool
    tool_history_fidelity: bool
    cache_metadata_preserved: bool
    resume_continuity: bool
    unknown_native_passthrough: bool

    def __post_init__(self) -> None:
        _require_evidence_id(self.evidence_id)
        _require_bool_fields(
            self,
            (
                "inventory_complete",
                "model_scope_exact",
                "hard_bypass_complete",
                "thinking_stripped_control_reducible",
                "protected_prefix_exact",
                "token_off_on_wire_equivalent",
                "tool_history_fidelity",
                "cache_metadata_preserved",
                "resume_continuity",
                "unknown_native_passthrough",
            ),
        )

    @property
    def complete(self) -> bool:
        return all(
            (
                self.inventory_complete,
                self.model_scope_exact,
                self.hard_bypass_complete,
                self.thinking_stripped_control_reducible,
                self.protected_prefix_exact,
                self.token_off_on_wire_equivalent,
                self.tool_history_fidelity,
                self.cache_metadata_preserved,
                self.resume_continuity,
                self.unknown_native_passthrough,
            )
        )


@dataclass(frozen=True, slots=True)
class AnthropicPreservedThinkingLiveEvidence:
    evidence_id: str
    model_id: str
    binding_beta: str
    prefix_mismatch_behavior: str
    cache_hit_observed: bool
    tool_history_fidelity: bool
    resume_continuity: bool
    prefix_binding_observed: bool
    input_transformations_clear: bool
    usage_complete: bool
    estimated_cost_usd: str
    accounting_status: str

    def __post_init__(self) -> None:
        _require_evidence_id(self.evidence_id)
        if not isinstance(self.model_id, str) or not self.model_id:
            raise ValueError("model_id must be non-blank")
        if self.binding_beta != BINDING_BETA:
            raise ValueError("unsupported binding beta")
        if self.prefix_mismatch_behavior != BINDING_MODE:
            raise ValueError("unsupported prefix mismatch behavior")
        _require_bool_fields(
            self,
            (
                "cache_hit_observed",
                "tool_history_fidelity",
                "resume_continuity",
                "prefix_binding_observed",
                "input_transformations_clear",
                "usage_complete",
            ),
        )
        _require_nonnegative_finite_decimal(self.estimated_cost_usd, "estimated_cost_usd")
        if self.accounting_status not in ACCOUNTING_STATES:
            raise ValueError("unsupported accounting_status")

    @property
    def complete(self) -> bool:
        return (
            self.model_id == MODEL_ID
            and self.cache_hit_observed
            and self.tool_history_fidelity
            and self.resume_continuity
            and self.prefix_binding_observed
            and self.input_transformations_clear
            and self.usage_complete
        )


def _combined_evidence_id(*evidence_ids: str) -> str:
    normalized = tuple(sorted(set(evidence_ids)))
    encoded = json.dumps(list(normalized), separators=(",", ":")).encode("utf-8")
    return f"anthropic-pt:{sha256(encoded).hexdigest()}"


def build_anthropic_preserved_thinking_generation(
    evidence_ids: tuple[str, ...],
) -> BenchmarkGeneration:
    normalized = tuple(sorted(set(evidence_ids)))
    if not normalized or any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise ValueError("evidence_ids must contain non-blank values")
    encoded = json.dumps(list(normalized), separators=(",", ":")).encode("utf-8")
    return BenchmarkGeneration(
        generation_id=GENERATION_ID,
        schema_version=1,
        corpus_version=CORPUS_VERSION,
        evaluator_version=EVALUATOR_VERSION,
        policy_version=POLICY_VERSION,
        evidence_digest=sha256(encoded).hexdigest(),
        evidence_ids=normalized,
    )


def classify_anthropic_preserved_thinking(
    offline: AnthropicPreservedThinkingOfflineEvidence,
    live: AnthropicPreservedThinkingLiveEvidence | None,
) -> CompatibilityRecord:
    if not offline.complete:
        return CompatibilityRecord(
            key=ANTHROPIC_PRESERVED_THINKING_KEY,
            state=CompatibilityState.PASSTHROUGH_ONLY,
            evidence_id=offline.evidence_id,
            reason="offline_contract_incomplete",
        )
    if live is None:
        return CompatibilityRecord(
            key=ANTHROPIC_PRESERVED_THINKING_KEY,
            state=CompatibilityState.PASSTHROUGH_ONLY,
            evidence_id=offline.evidence_id,
            reason="offline_conformance_only",
        )

    evidence_id = _combined_evidence_id(offline.evidence_id, live.evidence_id)
    if not live.complete:
        return CompatibilityRecord(
            key=ANTHROPIC_PRESERVED_THINKING_KEY,
            state=CompatibilityState.PASSTHROUGH_ONLY,
            evidence_id=evidence_id,
            reason="live_contract_incomplete",
        )
    return CompatibilityRecord(
        key=ANTHROPIC_PRESERVED_THINKING_KEY,
        state=CompatibilityState.PASSTHROUGH_ONLY,
        evidence_id=evidence_id,
        reason="live_canary_candidate",
    )
