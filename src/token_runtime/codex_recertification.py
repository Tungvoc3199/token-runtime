from __future__ import annotations

from dataclasses import dataclass

from .capabilities import CapabilityDetector, CapabilityKey, CapabilityProfile, CapabilityRegistry
from .compatibility import CompatibilityRecord, CompatibilityRegistry, CompatibilityState
from .openai_certification import CertificationEvidence


CODEX_01540_RESPONSES_KEY = CapabilityKey(
    "codex",
    "responses",
    "openai-compatible",
    client_version="0.154.0",
)


@dataclass(frozen=True, slots=True)
class CodexRecertArea:
    area: str
    state: CompatibilityState
    evidence_id: str
    reason: str

    def to_primitive(self) -> dict[str, str]:
        return {
            "area": self.area,
            "state": self.state.value,
            "evidence_id": self.evidence_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Codex01540RecertificationBundle:
    profile: CapabilityProfile
    record: CompatibilityRecord
    evidence: CertificationEvidence
    areas: tuple[CodexRecertArea, ...]
    detector: CapabilityDetector

    def to_primitive(self) -> dict[str, object]:
        return {
            "profile": self.profile.to_primitive(),
            "record": {
                "state": self.record.state.value,
                "evidence_id": self.record.evidence_id,
                "reason": self.record.reason,
            },
            "evidence": self.evidence.to_primitive(),
            "areas": [item.to_primitive() for item in self.areas],
        }


def _area(area: str, state: CompatibilityState, reason: str) -> CodexRecertArea:
    return CodexRecertArea(
        area=area,
        state=state,
        evidence_id="token-codex-01540-recert-1",
        reason=reason,
    )


def build_codex_01540_recertification() -> Codex01540RecertificationBundle:
    evidence = CertificationEvidence(
        evidence_id="token-codex-01540-recert-1:responses-boundary",
        version_scope="codex-cli-0.154.0",
        scope="codex-responses/request-response-boundary",
        assertion_ids=(
            "exact-binary-checksum",
            "responses-direct-loopback",
            "responses-via-token-loopback",
            "responses-request-byte-replay",
            "cached-token-response-byte-fidelity",
            "resume-history-continuity",
            "fork-history-continuity",
        ),
    )
    profile = CapabilityProfile(
        key=CODEX_01540_RESPONSES_KEY,
        tool_calls=True,
        reasoning_state="opaque-preserved",
        streaming=True,
        exact_byte_preservation=True,
        evidence_id=evidence.evidence_id,
    )
    record = CompatibilityRecord(
        key=CODEX_01540_RESPONSES_KEY,
        state=CompatibilityState.CERTIFIED,
        evidence_id=evidence.evidence_id,
        reason="request_boundary_certified",
    )
    capabilities = CapabilityRegistry()
    compatibility = CompatibilityRegistry()
    capabilities.register(profile)
    compatibility.register(record)
    areas = (
        _area("responses_request_fidelity", CompatibilityState.CERTIFIED, "exact_loopback_replay"),
        _area("responses_response_fidelity", CompatibilityState.CERTIFIED, "opaque_stream_forwarding"),
        _area("token_off_on_boundary", CompatibilityState.CERTIFIED, "exact_request_boundary_observed"),
        _area("native_context_compaction", CompatibilityState.PASSTHROUGH_ONLY, "native_internal_state_not_observed_by_token"),
        _area("authorization_across_compaction", CompatibilityState.PASSTHROUGH_ONLY, "native_authorization_state_not_observed_by_token"),
        _area("resume_fork_continuity", CompatibilityState.CERTIFIED, "exact_cli_history_continuity_observed"),
        _area("long_context_continuity", CompatibilityState.PASSTHROUGH_ONLY, "long_context_compaction_semantics_not_observed_end_to_end"),
        _area("dynamic_plugin_skill_refresh", CompatibilityState.PASSTHROUGH_ONLY, "dynamic_session_capabilities_not_consumed_by_token"),
        _area("mcp_oauth_rejected_no_replay", CompatibilityState.PASSTHROUGH_ONLY, "mcp_transport_outside_token_gateway_boundary"),
        _area("prompt_server_cache_semantics", CompatibilityState.PASSTHROUGH_ONLY, "provider_cache_and_billing_not_observed_locally"),
    )
    return Codex01540RecertificationBundle(
        profile=profile,
        record=record,
        evidence=evidence,
        areas=areas,
        detector=CapabilityDetector(capabilities, compatibility),
    )
