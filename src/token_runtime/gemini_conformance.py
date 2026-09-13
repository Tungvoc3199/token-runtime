from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace

from .capabilities import (
    CapabilityDetector,
    CapabilityKey,
    CapabilityProfile,
    CapabilityRegistry,
)
from .compatibility import (
    CompatibilityRecord,
    CompatibilityRegistry,
    CompatibilityState,
)
from .conformance import ConformanceResult, require_conformance, run_conformance
from .gemini_adapter import GeminiGenerateContentAdapter


GEMINI_GENERATE_CONTENT_KEY = CapabilityKey(
    "generic-google",
    "gemini_generate_content",
    "google",
)
EVIDENCE_ID = "token-gemini-adapter-1:offline-request-boundary-v1"


@dataclass(frozen=True, slots=True)
class GeminiConformanceBundle:
    profile: CapabilityProfile
    record: CompatibilityRecord
    detector: CapabilityDetector


def build_gemini_conformance() -> GeminiConformanceBundle:
    profile = CapabilityProfile(
        key=GEMINI_GENERATE_CONTENT_KEY,
        server_cache="cached-content-reference-preserved",
        tool_calls=True,
        reasoning_state="exact-replay-required",
        exact_byte_preservation=True,
        evidence_id=EVIDENCE_ID,
    )
    record = CompatibilityRecord(
        key=GEMINI_GENERATE_CONTENT_KEY,
        state=CompatibilityState.PASSTHROUGH_ONLY,
        evidence_id=EVIDENCE_ID,
        reason="offline_conformance_only",
    )
    capabilities = CapabilityRegistry()
    capabilities.register(profile)
    compatibility = CompatibilityRegistry()
    compatibility.register(record)
    return GeminiConformanceBundle(
        profile=profile,
        record=record,
        detector=CapabilityDetector(capabilities, compatibility),
    )


def _supported_fixture() -> dict[str, object]:
    return {
        "contents": [
            {"role": "user", "parts": [{"text": "current task"}]},
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "id": "call_1",
                            "name": "lookup",
                            "args": {"q": "status"},
                        }
                    }
                ],
            },
        ],
        "systemInstruction": {"parts": [{"text": "stable policy"}]},
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "lookup",
                        "description": "fixture",
                        "parameters": {"type": "OBJECT"},
                    }
                ]
            }
        ],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "cachedContent": "cachedContents/cache-1",
        "generationConfig": {"temperature": 0.2, "thinkingLevel": "LOW"},
        "futureField": {"preserve": True},
    }


def _supported_roundtrip() -> bool:
    payload = _supported_fixture()
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return envelope.wire_safe and adapter.serialize(envelope) == payload


def _roleless_text_roundtrip() -> bool:
    payload = {"contents": [{"parts": [{"text": "hello"}]}]}
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    user = next((block for block in envelope.blocks if block.text == "hello"), None)
    return (
        envelope.wire_safe
        and user is not None
        and user.kind == "user"
        and user.role == "user"
        and user.metadata.get("path") == ("contents", 0, "parts", 0, "text")
        and adapter.serialize(envelope) == payload
    )


def _cached_content_reference_preserved() -> bool:
    payload = _supported_fixture()
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    serialized = adapter.serialize(envelope)
    return (
        envelope.wire_safe
        and serialized == payload
        and serialized["cachedContent"] == "cachedContents/cache-1"
    )


def _text_path_mutation_preserves_protocol() -> bool:
    payload = _supported_fixture()
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    target = next(block for block in envelope.blocks if block.text == "current task")
    changed = replace(
        envelope,
        blocks=tuple(
            replace(block, text="updated task") if block is target else block
            for block in envelope.blocks
        ),
    )
    actual = adapter.serialize(changed)
    expected = deepcopy(payload)
    expected["contents"][0]["parts"][0]["text"] = "updated task"
    return actual == expected


def _system_instruction_text_mutation() -> bool:
    payload = _supported_fixture()
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    target = next(block for block in envelope.blocks if block.kind == "system")
    changed = replace(
        envelope,
        blocks=tuple(
            replace(block, text="updated policy") if block is target else block
            for block in envelope.blocks
        ),
    )
    actual = adapter.serialize(changed)
    expected = deepcopy(payload)
    expected["systemInstruction"]["parts"][0]["text"] = "updated policy"
    return actual == expected


def _tool_classification() -> bool:
    call_payload = _supported_fixture()
    call_envelope = GeminiGenerateContentAdapter().parse(call_payload)
    call_by_kind = {block.kind: block for block in call_envelope.blocks}
    call_required = {"tool_schema", "tool_call"}

    response_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": "call_1",
                            "name": "lookup",
                            "response": {"status": "green"},
                        }
                    }
                ],
            }
        ]
    }
    response_envelope = GeminiGenerateContentAdapter().parse(response_payload)
    output = next(
        block for block in response_envelope.blocks if block.kind == "tool_output"
    )
    return (
        call_envelope.wire_safe
        and call_required <= set(call_by_kind)
        and all("path" not in call_by_kind[kind].metadata for kind in call_required)
        and not response_envelope.wire_safe
        and "path" not in output.metadata
        and GeminiGenerateContentAdapter().serialize(response_envelope) == response_payload
    )


def _function_response_exact_passthrough() -> bool:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "lookup",
                            "response": {"status": "green"},
                        }
                    }
                ],
            }
        ]
    }
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return (
        not envelope.wire_safe
        and any(block.kind == "tool_output" for block in envelope.blocks)
        and adapter.serialize(envelope) == payload
    )


def _thought_signature_exact_passthrough() -> bool:
    payload = {
        "contents": [
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {"name": "lookup", "args": {"q": "x"}},
                        "thoughtSignature": "opaque-signature",
                    }
                ],
            }
        ]
    }
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return (
        not envelope.wire_safe
        and adapter.serialize(envelope) == payload
        and any(block.kind == "protocol_state" for block in envelope.blocks)
    )


def _unknown_multimodal_passthrough() -> bool:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "describe"},
                    {"inlineData": {"mimeType": "image/png", "data": "opaque"}},
                ],
            }
        ]
    }
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _unsupported_tool_passthrough() -> bool:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "search"}]}],
        "tools": [{"googleSearch": {}}],
    }
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _malformed_function_passthrough() -> bool:
    payload = {
        "contents": [
            {"role": "model", "parts": [{"functionCall": {"args": {"q": "x"}}}]}
        ]
    }
    adapter = GeminiGenerateContentAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _streaming_unclaimed() -> bool:
    bundle = build_gemini_conformance()
    return (
        bundle.profile.streaming == "unknown"
        and GeminiGenerateContentAdapter.protocol_id == "gemini_generate_content"
    )


def _certification_state_passthrough_only() -> bool:
    bundle = build_gemini_conformance()
    return (
        bundle.record.state is CompatibilityState.PASSTHROUGH_ONLY
        and bundle.record.reason == "offline_conformance_only"
        and bundle.profile.evidence_id == bundle.record.evidence_id
    )


def _near_match_non_inheritance() -> bool:
    bundle = build_gemini_conformance()
    keys = (
        CapabilityKey(
            "generic-google",
            "gemini_generate_content",
            "google",
            model_family="gemini-future",
        ),
        CapabilityKey("generic-google", "gemini_generate_content", "google-v2"),
        CapabilityKey("gemini-cli", "gemini_generate_content", "google"),
    )
    return all(
        bundle.detector.detect(key).profile is None
        and bundle.detector.detect(key).compatibility.state
        is CompatibilityState.PASSTHROUGH_ONLY
        and bundle.detector.detect(key).compatibility.reason == "unknown_capability"
        for key in keys
    )


def gemini_conformance_cases() -> Mapping[str, Callable[[], bool]]:
    return {
        "cached_content_reference_preserved": _cached_content_reference_preserved,
        "certification_state_passthrough_only": _certification_state_passthrough_only,
        "function_response_exact_passthrough": _function_response_exact_passthrough,
        "malformed_function_passthrough": _malformed_function_passthrough,
        "near_match_non_inheritance": _near_match_non_inheritance,
        "roleless_text_roundtrip": _roleless_text_roundtrip,
        "streaming_unclaimed": _streaming_unclaimed,
        "supported_roundtrip": _supported_roundtrip,
        "system_instruction_text_mutation": _system_instruction_text_mutation,
        "text_path_mutation_preserves_protocol": _text_path_mutation_preserves_protocol,
        "thought_signature_exact_passthrough": _thought_signature_exact_passthrough,
        "tool_classification": _tool_classification,
        "unknown_multimodal_passthrough": _unknown_multimodal_passthrough,
        "unsupported_tool_passthrough": _unsupported_tool_passthrough,
    }


def run_gemini_conformance() -> tuple[ConformanceResult, ...]:
    results = run_conformance(gemini_conformance_cases())
    require_conformance(results)
    return results
