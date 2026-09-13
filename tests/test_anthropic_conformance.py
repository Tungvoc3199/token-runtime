import unittest

from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import CompatibilityState
from token_runtime.anthropic_conformance import (
    ANTHROPIC_MESSAGES_KEY,
    AnthropicConformanceBundle,
    build_anthropic_conformance,
    anthropic_conformance_cases,
    run_anthropic_conformance,
)


class AnthropicConformanceBundleTests(unittest.TestCase):
    def test_bundle_is_model_agnostic_and_passthrough_only(self):
        bundle = build_anthropic_conformance()
        self.assertIsInstance(bundle, AnthropicConformanceBundle)
        self.assertEqual(bundle.profile.key, ANTHROPIC_MESSAGES_KEY)
        self.assertIsNone(bundle.profile.key.model_family)
        self.assertEqual(bundle.record.key, ANTHROPIC_MESSAGES_KEY)
        self.assertEqual(
            bundle.record.state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )
        self.assertEqual(bundle.record.reason, "offline_conformance_only")
        self.assertEqual(bundle.profile.evidence_id, bundle.record.evidence_id)

    def test_profile_claims_only_bounded_request_facts(self):
        profile = build_anthropic_conformance().profile
        self.assertIs(profile.exact_byte_preservation, True)
        self.assertIs(profile.tool_calls, True)
        self.assertEqual(profile.prompt_cache, "request-markers-preserved")
        self.assertEqual(profile.reasoning_state, "exact-replay-required")
        self.assertEqual(profile.multimodal, "unknown")
        self.assertEqual(profile.native_context_management, "unknown")
        self.assertEqual(profile.streaming, "unknown")

    def test_near_match_and_model_name_do_not_inherit_profile(self):
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
            self.assertIsNone(detected.profile)
            self.assertEqual(
                detected.compatibility.state,
                CompatibilityState.PASSTHROUGH_ONLY,
            )
            self.assertEqual(detected.compatibility.reason, "unknown_capability")


class AnthropicConformanceCasesTests(unittest.TestCase):
    def test_conformance_cases_are_deterministic_and_green(self):
        cases = anthropic_conformance_cases()
        self.assertEqual(
            tuple(sorted(cases)),
            (
                "cache_markers_preserved",
                "certification_state_passthrough_only",
                "cited_text_exact_passthrough",
                "near_match_non_inheritance",
                "stream_preserved",
                "supported_roundtrip",
                "text_path_mutation_preserves_protocol",
                "thinking_exact_passthrough",
                "tool_classification",
                "unknown_multimodal_passthrough",
            ),
        )
        self.assertTrue(all(case() is True for case in cases.values()))
        results = run_anthropic_conformance()
        self.assertEqual(
            tuple(result.name for result in results),
            tuple(sorted(cases)),
        )
        self.assertTrue(all(result.passed for result in results))


if __name__ == "__main__":
    unittest.main()
