from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .capabilities import CapabilityDetector, CapabilityKey
from .compatibility import CompatibilityState
from .contracts import AgentIntegrationContract
from .feature_flags import (
    FeatureEffect,
    FeatureFlagState,
    permitted_effect,
)


class AgentIntegrationMode(str, Enum):
    TOKEN = "TOKEN"
    PASSTHROUGH = "PASSTHROUGH"


@dataclass(frozen=True, slots=True)
class AgentIntegrationDecision:
    agent_id: str
    capability_key: CapabilityKey
    endpoint: str
    compatibility_state: CompatibilityState
    effect: FeatureEffect
    evidence_id: str
    reason: str | None
    mode: AgentIntegrationMode


class AgentIntegrationFramework:
    def __init__(
        self,
        detector: CapabilityDetector,
        *,
        flag_state: FeatureFlagState = FeatureFlagState.ENABLED,
    ) -> None:
        self.detector = detector
        self.flag_state = flag_state

    def resolve(
        self,
        integration: AgentIntegrationContract,
    ) -> AgentIntegrationDecision:
        detected = self.detector.detect(integration.capability_key)
        if detected.profile is None:
            compatibility_state = CompatibilityState.PASSTHROUGH_ONLY
            evidence_id = "unknown"
            reason = (
                "unknown_capability"
                if detected.compatibility.reason == "unknown_capability"
                else "missing_capability_profile"
            )
        elif detected.compatibility.reason == "unknown_capability":
            compatibility_state = CompatibilityState.PASSTHROUGH_ONLY
            evidence_id = "unknown"
            reason = "unknown_capability"
        elif (
            detected.profile.evidence_id == "unknown"
            or detected.compatibility.evidence_id == "unknown"
            or detected.profile.evidence_id != detected.compatibility.evidence_id
        ):
            compatibility_state = CompatibilityState.PASSTHROUGH_ONLY
            evidence_id = "unknown"
            reason = "capability_evidence_mismatch"
        else:
            compatibility_state = detected.compatibility.state
            evidence_id = detected.compatibility.evidence_id
            reason = detected.compatibility.reason
        effect = permitted_effect(self.flag_state, compatibility_state)
        mode = (
            AgentIntegrationMode.TOKEN
            if effect is FeatureEffect.EXECUTE
            else AgentIntegrationMode.PASSTHROUGH
        )
        return AgentIntegrationDecision(
            agent_id=integration.agent_id,
            capability_key=integration.capability_key,
            endpoint=integration.endpoint,
            compatibility_state=compatibility_state,
            effect=effect,
            evidence_id=evidence_id,
            reason=reason,
            mode=mode,
        )


@dataclass(frozen=True, slots=True)
class _AgentIntegrationDescriptor:
    agent_id: str
    capability_key: CapabilityKey
    endpoint: str


def codex_01540_reference() -> AgentIntegrationContract:
    from .codex_recertification import CODEX_01540_RESPONSES_KEY

    return _AgentIntegrationDescriptor(
        agent_id="codex",
        capability_key=CODEX_01540_RESPONSES_KEY,
        endpoint="/v1/responses",
    )


def build_codex_01540_agent_framework(
    *,
    flag_state: FeatureFlagState = FeatureFlagState.ENABLED,
) -> AgentIntegrationFramework:
    from .codex_recertification import build_codex_01540_recertification

    bundle = build_codex_01540_recertification()
    return AgentIntegrationFramework(bundle.detector, flag_state=flag_state)
