import json
import unittest

from token_runtime.adapters import ChatCompletionsAdapter, ResponsesAdapter
from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import CompatibilityState
from token_runtime.openai_certification import (
    CODEX_RESPONSES_KEY,
    CertificationEvidence,
    OPENAI_CHAT_COMPLETIONS_KEY,
    OPENAI_RESPONSES_KEY,
    OpenAICertificationBundle,
    build_openai_certification,
    openai_conformance_cases,
    run_openai_conformance,
)


class OpenAICertificationBundleTests(unittest.TestCase):
    def test_bundle_contains_exactly_three_certified_request_boundaries(self):
        bundle = build_openai_certification()
        self.assertIsInstance(bundle, OpenAICertificationBundle)
        expected = (
            CODEX_RESPONSES_KEY,
            OPENAI_CHAT_COMPLETIONS_KEY,
            OPENAI_RESPONSES_KEY,
        )
        self.assertEqual(tuple(profile.key for profile in bundle.profiles), expected)
        self.assertEqual(tuple(record.key for record in bundle.records), expected)
        self.assertEqual(
            tuple(record.state for record in bundle.records),
            (CompatibilityState.CERTIFIED,) * 3,
        )
        self.assertEqual(len(bundle.evidence), 3)
        self.assertEqual(len({item.evidence_id for item in bundle.evidence}), 3)
        generic = [item for item in bundle.evidence if "codex" not in item.evidence_id]
        self.assertEqual(
            {item.version_scope for item in generic},
            {"token-request-contract-v1"},
        )

    def test_profiles_are_conservative_and_model_agnostic(self):
        bundle = build_openai_certification()
        for profile in bundle.profiles:
            self.assertIsNone(profile.key.model_family)
            self.assertIs(profile.exact_byte_preservation, True)
            self.assertIs(profile.tool_calls, True)
            self.assertEqual(profile.reasoning_state, "opaque-preserved")
            self.assertEqual(profile.multimodal, "unknown")
            self.assertEqual(profile.native_context_management, "unknown")

    def test_near_match_is_not_promoted_by_model_name(self):
        bundle = build_openai_certification()
        near_match = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            "future-model",
         )
        detected = bundle.detector.detect(near_match)
        self.assertIsNone(detected.profile)
        self.assertEqual(
            detected.compatibility.state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )
        self.assertEqual(detected.compatibility.reason, "unknown_capability")


class OpenAIProtocolConformanceTests(unittest.TestCase):
    def test_responses_text_tool_fixture_round_trips_exactly(self):
        payload = {
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
        adapter = ResponsesAdapter()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)

    def test_chat_completions_text_tool_fixture_round_trips_exactly(self):
        payload = {
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
        adapter = ChatCompletionsAdapter()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)

    def test_unsupported_multimodal_shapes_fail_safe_and_round_trip_exactly(self):
        responses_payload = {
            "model": "opaque-model",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": "fixture://image"}],
                }
            ],
            "future_field": {"preserve": True},
        }
        responses = ResponsesAdapter()
        response_envelope = responses.parse(responses_payload)
        self.assertFalse(response_envelope.wire_safe)
        self.assertEqual(responses.serialize(response_envelope), responses_payload)

        chat_payload = {
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
        chat = ChatCompletionsAdapter()
        chat_envelope = chat.parse(chat_payload)
        self.assertFalse(chat_envelope.wire_safe)
        self.assertEqual(chat.serialize(chat_envelope), chat_payload)

    def test_protocol_conformance_suite_is_deterministic_and_green(self):
        cases = openai_conformance_cases()
        self.assertEqual(
            tuple(sorted(cases)),
            (
                "certification_matrix",
                "chat_completions_roundtrip",
                "chat_completions_unsupported_passthrough",
                "responses_roundtrip",
                "responses_unsupported_passthrough",
                "unknown_key_passthrough",
            ),
        )
        self.assertTrue(all(case() is True for case in cases.values()))
        results = run_openai_conformance()
        self.assertEqual(
            tuple(result.name for result in results),
            tuple(sorted(cases)),
        )
        self.assertTrue(all(result.passed for result in results))


class CertificationEvidenceTests(unittest.TestCase):
    def test_evidence_serialization_is_deterministic_and_public_safe(self):
        evidence = CertificationEvidence(
            evidence_id="token-openai-cert-1:fixture",
            version_scope="protocol-v1",
            scope="request-boundary",
            assertion_ids=("b-assertion", "a-assertion"),
        )
        self.assertEqual(
            evidence.to_primitive(),
            {
                "evidence_id": "token-openai-cert-1:fixture",
                "version_scope": "protocol-v1",
                "scope": "request-boundary",
                "assertion_ids": ["b-assertion", "a-assertion"],
            },
        )

        bundle = build_openai_certification()
        primitive = [item.to_primitive() for item in bundle.evidence]
        encoded = json.dumps(primitive, sort_keys=True, separators=(",", ":"))
        self.assertEqual(
            [item["evidence_id"] for item in primitive],
            sorted(item["evidence_id"] for item in primitive),
        )
        for forbidden in (
            "/home/",
            "127.0.0.1",
            "resp_",
            "authorization",
            "api_key",
        ):
            self.assertNotIn(forbidden, encoded.lower())


class CodexClientVersionIsolationTests(unittest.TestCase):
    def test_codex_certification_key_encodes_exact_client_version(self):
        self.assertEqual(getattr(CODEX_RESPONSES_KEY, "client_version", None), "0.153.4")


if __name__ == "__main__":
    unittest.main()
