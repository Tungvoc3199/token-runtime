from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from .anthropic_adapter import AnthropicMessagesAdapter
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


ANTHROPIC_MESSAGES_KEY = CapabilityKey(
    "generic-anthropic",
    "anthropic_messages",
    "anthropic",
)
EVIDENCE_ID = "token-anthropic-adapter-1:offline-request-boundary-v1"


@dataclass(frozen=True, slots=True)
class AnthropicConformanceBundle:
    profile: CapabilityProfile
    record: CompatibilityRecord
    detector: CapabilityDetector


def build_anthropic_conformance() -> AnthropicConformanceBundle:
    profile = CapabilityProfile(
        key=ANTHROPIC_MESSAGES_KEY,
        prompt_cache="request-markers-preserved",
        tool_calls=True,
        reasoning_state="exact-replay-required",
        exact_byte_preservation=True,
        evidence_id=EVIDENCE_ID,
    )
    record = CompatibilityRecord(
        key=ANTHROPIC_MESSAGES_KEY,
        state=CompatibilityState.PASSTHROUGH_ONLY,
        evidence_id=EVIDENCE_ID,
        reason="offline_conformance_only",
    )
    capabilities = CapabilityRegistry()
    capabilities.register(profile)
    compatibility = CompatibilityRegistry()
    compatibility.register(record)
    return AnthropicConformanceBundle(
        profile=profile,
        record=record,
        detector=CapabilityDetector(capabilities, compatibility),
    )


def _supported_fixture() -> dict[str, object]:
    return {
        "model": "opaque-model",
        "max_tokens": 256,
        "system": [
            {
                "type": "text",
                "text": "stable policy",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {"role": "user", "content": "current task"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "query",
                        "input": {"q": "status"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "status=green",
                    }
                ],
            },
        ],
        "tools": [
            {
                "name": "query",
                "description": "fixture",
                "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "stream": True,
        "future_field": {"preserve": True},
    }


def _supported_roundtrip() -> bool:
    payload = _supported_fixture()
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    return envelope.wire_safe and adapter.serialize(envelope) == payload


def _cache_markers_preserved() -> bool:
    payload = _supported_fixture()
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    serialized = adapter.serialize(envelope)
    return (
        serialized == payload
        and serialized["system"][0]["cache_control"] == {"type": "ephemeral"}
        and serialized["tools"][0]["cache_control"] == {"type": "ephemeral"}
    )



def _text_path_mutation_preserves_protocol() -> bool:
    payload = _supported_fixture()
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    target = next(block for block in envelope.blocks if block.text == "current task")
    changed = replace(
        envelope,
        blocks=tuple(
            replace(block, text="updated task") if block is target else block
            for block in envelope.blocks
        ),
    )
    serialized = adapter.serialize(changed)
    return (
        serialized["messages"][0]["content"] == "updated task"
        and serialized["messages"][1:] == payload["messages"][1:]
        and serialized["system"] == payload["system"]
        and serialized["tools"] == payload["tools"]
        and serialized["future_field"] == payload["future_field"]
    )


def _tool_classification() -> bool:
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(_supported_fixture())
    tool_call = next(block for block in envelope.blocks if block.kind == "tool_call")
    tool_output = next(block for block in envelope.blocks if block.kind == "tool_output")
    return (
        envelope.wire_safe
        and "path" not in tool_call.metadata
        and tool_output.role == "tool"
        and tool_output.metadata.get("path")
        == ("messages", 2, "content", 0, "content")
    )


def _stream_preserved() -> bool:
    payload = _supported_fixture()
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    serialized = adapter.serialize(envelope)
    return envelope.wire_safe and serialized.get("stream") is True


def _near_match_non_inheritance() -> bool:
    bundle = build_anthropic_conformance()
    near_matches = (
        CapabilityKey(
            "generic-anthropic",
            "anthropic_messages",
            "anthropic",
            model_family="claude-future",
        ),
        CapabilityKey("generic-anthropic", "anthropic_messages", "anthropic-v2"),
    )
    for key in near_matches:
        detected = bundle.detector.detect(key)
        if detected.profile is not None:
            return False
        if detected.compatibility.state is not CompatibilityState.PASSTHROUGH_ONLY:
            return False
        if detected.compatibility.reason != "unknown_capability":
            return False
    return True


def _cited_text_exact_passthrough() -> bool:
    payload = {
        "model": "opaque-model",
        "max_tokens": 128,
        "system": [
            {
                "type": "text",
                "text": "cited system",
                "citations": [{"type": "char_location", "cited_text": "cited"}],
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "cited message",
                        "citations": [
                            {"type": "char_location", "cited_text": "cited"}
                        ],
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_cited",
                        "name": "query",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_cited",
                        "content": [
                            {
                                "type": "text",
                                "text": "cited tool result",
                                "citations": [
                                    {
                                        "type": "char_location",
                                        "cited_text": "cited",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    cited_blocks = [block for block in envelope.blocks if block.text.startswith("cited")]
    return (
        not envelope.wire_safe
        and len(cited_blocks) == 3
        and all("path" not in block.metadata for block in cited_blocks)
        and adapter.serialize(envelope) == payload
    )

def _thinking_exact_passthrough() -> bool:
    payload = {
        "model": "opaque-model",
        "max_tokens": 64,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "opaque", "signature": "sig"}
                ],
            },
            {"role": "user", "content": "continue"},
        ],
    }
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _unknown_multimodal_passthrough() -> bool:
    payload = {
        "model": "opaque-model",
        "max_tokens": 64,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "fixture",
                        },
                    }
                ],
            }
        ],
        "future_field": {"preserve": True},
    }
    adapter = AnthropicMessagesAdapter()
    envelope = adapter.parse(payload)
    return not envelope.wire_safe and adapter.serialize(envelope) == payload


def _certification_state_passthrough_only() -> bool:
    bundle = build_anthropic_conformance()
    return (
        bundle.record.state is CompatibilityState.PASSTHROUGH_ONLY
        and bundle.record.reason == "offline_conformance_only"
        and bundle.profile.evidence_id == bundle.record.evidence_id
    )


def anthropic_conformance_cases() -> Mapping[str, Callable[[], bool]]:
    return {
        "cache_markers_preserved": _cache_markers_preserved,
        "certification_state_passthrough_only": _certification_state_passthrough_only,
        "cited_text_exact_passthrough": _cited_text_exact_passthrough,
        "near_match_non_inheritance": _near_match_non_inheritance,
        "stream_preserved": _stream_preserved,
        "supported_roundtrip": _supported_roundtrip,
        "text_path_mutation_preserves_protocol": _text_path_mutation_preserves_protocol,
        "thinking_exact_passthrough": _thinking_exact_passthrough,
        "tool_classification": _tool_classification,
        "unknown_multimodal_passthrough": _unknown_multimodal_passthrough,
    }


def run_anthropic_conformance() -> tuple[ConformanceResult, ...]:
    results = run_conformance(anthropic_conformance_cases())
    require_conformance(results)
    return results
