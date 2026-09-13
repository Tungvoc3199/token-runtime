from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .compatibility import CompatibilityRecord, CompatibilityRegistry


UnknownBool = bool | Literal["unknown"]


@dataclass(frozen=True, order=True, slots=True)
class CapabilityKey:
    client_family: str
    protocol_family: str
    provider_family: str
    model_family: str | None = None
    client_version: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    key: CapabilityKey
    context_window_semantics: str = "unknown"
    tokenizer_family: str = "unknown"
    prompt_cache: str = "unknown"
    server_cache: str = "unknown"
    stateful_sessions: UnknownBool = "unknown"
    native_context_management: UnknownBool = "unknown"
    structured_output: UnknownBool = "unknown"
    tool_calls: UnknownBool = "unknown"
    multimodal: UnknownBool = "unknown"
    reasoning_state: str = "unknown"
    streaming: UnknownBool = "unknown"
    exact_byte_preservation: UnknownBool = "unknown"
    evidence_id: str = "unknown"

    def to_primitive(self) -> dict[str, object]:
        key: dict[str, object] = {
            "client_family": self.key.client_family,
            "protocol_family": self.key.protocol_family,
            "provider_family": self.key.provider_family,
            "model_family": self.key.model_family,
        }
        if self.key.client_version:
            key["client_version"] = self.key.client_version
        return {
            "key": key,
            "context_window_semantics": self.context_window_semantics,
            "tokenizer_family": self.tokenizer_family,
            "prompt_cache": self.prompt_cache,
            "server_cache": self.server_cache,
            "stateful_sessions": self.stateful_sessions,
            "native_context_management": self.native_context_management,
            "structured_output": self.structured_output,
            "tool_calls": self.tool_calls,
            "multimodal": self.multimodal,
            "reasoning_state": self.reasoning_state,
            "streaming": self.streaming,
            "exact_byte_preservation": self.exact_byte_preservation,
            "evidence_id": self.evidence_id,
        }


class DuplicateCapabilityError(ValueError):
    pass


class CapabilityRegistry:
    def __init__(self) -> None:
        self._profiles: dict[CapabilityKey, CapabilityProfile] = {}

    def register(self, profile: CapabilityProfile) -> CapabilityProfile:
        existing = self._profiles.get(profile.key)
        if existing is None:
            self._profiles[profile.key] = profile
            return profile
        if existing == profile:
            return existing
        raise DuplicateCapabilityError(f"conflicting capability profile: {profile.key!r}")

    def get(self, key: CapabilityKey) -> CapabilityProfile | None:
        return self._profiles.get(key)

    def snapshot(self) -> tuple[CapabilityProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))


@dataclass(frozen=True, slots=True)
class CapabilityDetection:
    key: CapabilityKey
    profile: CapabilityProfile | None
    compatibility: "CompatibilityRecord"


class CapabilityDetector:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        compatibility: "CompatibilityRegistry",
    ) -> None:
        self.capabilities = capabilities
        self.compatibility = compatibility

    def detect(self, key: CapabilityKey) -> CapabilityDetection:
        return CapabilityDetection(
            key=key,
            profile=self.capabilities.get(key),
            compatibility=self.compatibility.get(key),
        )
