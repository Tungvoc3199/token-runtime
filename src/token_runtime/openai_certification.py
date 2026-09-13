from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .adapters import ChatCompletionsAdapter, ResponsesAdapter
from .capabilities import (
    CapabilityDetector,
    CapabilityKey,
    CapabilityProfile,
    CapabilityRegistry,
)
from .compatibility import (
    CompatibilityMatrix,
    CompatibilityRecord,
    CompatibilityRegistry,
    CompatibilityState,
)
from .conformance import ConformanceResult, require_conformance, run_conformance



CODEX_RESPONSES_KEY = CapabilityKey(
    "codex",
    "responses",
    "openai-compatible",
    client_version="0.153.4",
)
OPENAI_RESPONSES_KEY = CapabilityKey(
    "generic-openai",
    "responses",
    "openai-compatible",
)
OPENAI_CHAT_COMPLETIONS_KEY = CapabilityKey(
    "generic-openai",
    "chat_completions",
    "openai-compatible",
)


@dataclass(frozen=True, slots=True)
class CertificationEvidence:
    evidence_id: str
    version_scope: str
    scope: str
    assertion_ids: tuple[str, ...]

    def to_primitive(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "version_scope": self.version_scope,
            "scope": self.scope,
            "assertion_ids": list(self.assertion_ids),
        }


@dataclass(frozen=True, slots=True)
class OpenAICertificationBundle:
    profiles: tuple[CapabilityProfile, ...]
    records: tuple[CompatibilityRecord, ...]
    evidence: tuple[CertificationEvidence, ...]
    detector: CapabilityDetector
    matrix: CompatibilityMatrix


def _profile(key: CapabilityKey, evidence_id: str) -> CapabilityProfile:
    return CapabilityProfile(
        key=key,
        tool_calls=True,
        reasoning_state="opaque-preserved",
        streaming=True,
        exact_byte_preservation=True,
        evidence_id=evidence_id,
    )


def build_openai_certification() -> OpenAICertificationBundle:
    definitions = (
        (
            CODEX_RESPONSES_KEY,
            CertificationEvidence(
                evidence_id="token-openai-cert-1:codex-responses-0.153.4",
                version_scope="codex-cli-0.153.4",
                scope="codex-responses/request-boundary",
                assertion_ids=(
                    "codex-live-smoke-v1",
                    "responses-exact-roundtrip",
                    "unsupported-exact-passthrough",
                ),
            ),
        ),
        (
            OPENAI_CHAT_COMPLETIONS_KEY,
            CertificationEvidence(
                evidence_id="token-openai-cert-1:chat-completions-text-v1",
                version_scope="token-request-contract-v1",
                scope="openai-chat-completions/request-boundary-text-v1",
                assertion_ids=(
                    "chat-completions-exact-roundtrip",
                    "chat-completions-unsupported-exact-passthrough",
                ),
            ),
        ),
        (
            OPENAI_RESPONSES_KEY,
            CertificationEvidence(
                evidence_id="token-openai-cert-1:responses-text-v1",
                version_scope="token-request-contract-v1",
                scope="openai-responses/request-boundary-text-v1",
                assertion_ids=(
                    "responses-exact-roundtrip",
                    "responses-unsupported-exact-passthrough",
                ),
            ),
        ),
    )
    capabilities = CapabilityRegistry()
    compatibility = CompatibilityRegistry()
    evidence: list[CertificationEvidence] = []

    for key, item in definitions:
        capabilities.register(_profile(key, item.evidence_id))
        compatibility.register(
            CompatibilityRecord(
                key=key,
                state=CompatibilityState.CERTIFIED,
                evidence_id=item.evidence_id,
                reason="request_boundary_certified",
            )
        )
        evidence.append(item)

    return OpenAICertificationBundle(
        profiles=capabilities.snapshot(),
        records=compatibility.snapshot(),
        evidence=tuple(sorted(evidence, key=lambda item: item.evidence_id)),
        detector=CapabilityDetector(capabilities, compatibility),
        matrix=compatibility.matrix(),
    )


def _responses_fixture() -> dict[str, object]:
    return {
        "model": "opaque-model",
        "instructions": "Preserve exact constraints.",
        "input": [
            {"role": "developer", "content": "stable policy"},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "current task"}],
            },
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "query",
                "arguments": '{"q":"status"}',
            },
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "status=green",
            },
        ],
        "tools": [
            {
                "type": "function",
                "name": "query",
                "description": "fixture",
                "parameters": {"type": "object"},
            }
        ],
        "reasoning": {"effort": "medium"},
        "stream": True,
        "metadata": {"fixture": "c3"},
        "future_field": {"preserve": True},
    }


def _chat_completions_fixture() -> dict[str, object]:
    return {
        "model": "opaque-model",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "developer", "content": "developer"},
            {
                "role": "assistant",
                "content": "old",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "query", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "continue"}],
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "query", "parameters": {"type": "object"}},
            }
        ],
        "response_format": {"type": "json_object"},
        "stream": True,
        "future_field": {"preserve": True},
    }


def _responses_roundtrip() -> bool:
    payload = _responses_fixture()
    adapter = ResponsesAdapter()
    envelope = adapter.parse(payload)
    return envelope.wire_safe and adapter.serialize(envelope) == payload


def _chat_completions_roundtrip() -> bool:
    payload = _chat_completions_fixture()
    adapter = ChatCompletionsAdapter()
    envelope = adapter.parse(payload)
    return envelope.wire_safe and adapter.serialize(envelope) == payload


def _responses_unsupported_passthrough() -> bool:
    payload = {
        "model": "opaque-model",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_image", "image_url": "fixture://image"}],
            }
        ],
        "future_field": {"preserve": True},
    }
    adapter = ResponsesAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _chat_completions_unsupported_passthrough() -> bool:
    payload = {
        "model": "opaque-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "fixture://image"},
                    }
                ],
            }
        ],
        "future_field": {"preserve": True},
    }
    adapter = ChatCompletionsAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _certification_matrix_conforms() -> bool:
    bundle = build_openai_certification()
    expected = (
        CODEX_RESPONSES_KEY,
        OPENAI_CHAT_COMPLETIONS_KEY,
        OPENAI_RESPONSES_KEY,
    )
    return (
        tuple(profile.key for profile in bundle.profiles) == expected
        and tuple(record.key for record in bundle.records) == expected
        and all(record.state is CompatibilityState.CERTIFIED for record in bundle.records)
    )


def _unknown_key_passthrough() -> bool:
    bundle = build_openai_certification()
    unknown = bundle.detector.detect(
        CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            "future-model",
         )
    )
    return (
        unknown.profile is None
        and unknown.compatibility.state is CompatibilityState.PASSTHROUGH_ONLY
        and unknown.compatibility.reason == "unknown_capability"
    )


def openai_conformance_cases() -> Mapping[str, Callable[[], bool]]:
    return {
        "certification_matrix": _certification_matrix_conforms,
        "chat_completions_roundtrip": _chat_completions_roundtrip,
        "chat_completions_unsupported_passthrough": _chat_completions_unsupported_passthrough,
        "responses_roundtrip": _responses_roundtrip,
        "responses_unsupported_passthrough": _responses_unsupported_passthrough,
        "unknown_key_passthrough": _unknown_key_passthrough,
    }


def run_openai_conformance() -> tuple[ConformanceResult, ...]:
    results = run_conformance(openai_conformance_cases())
    require_conformance(results)
    return results
