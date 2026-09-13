import unittest

from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import CompatibilityState
from token_runtime.gemini_conformance import (
    GEMINI_GENERATE_CONTENT_KEY,
    GeminiConformanceBundle,
    build_gemini_conformance,
    gemini_conformance_cases,
    run_gemini_conformance,
)


class GeminiConformanceBundleTests(unittest.TestCase):
    def test_bundle_is_model_agnostic_and_passthrough_only(self):
        bundle = build_gemini_conformance()
        self.assertIsInstance(bundle, GeminiConformanceBundle)
        self.assertEqual(bundle.profile.key, GEMINI_GENERATE_CONTENT_KEY)
        self.assertIsNone(bundle.profile.key.model_family)
        self.assertEqual(bundle.record.key, GEMINI_GENERATE_CONTENT_KEY)
        self.assertEqual(bundle.record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(bundle.record.reason, "offline_conformance_only")
        self.assertEqual(bundle.profile.evidence_id, bundle.record.evidence_id)

    def test_profile_claims_only_bounded_request_facts(self):
        profile = build_gemini_conformance().profile
        self.assertIs(profile.exact_byte_preservation, True)
        self.assertIs(profile.tool_calls, True)
        self.assertEqual(profile.server_cache, "cached-content-reference-preserved")
        self.assertEqual(profile.reasoning_state, "exact-replay-required")
        self.assertEqual(profile.prompt_cache, "unknown")
        self.assertEqual(profile.multimodal, "unknown")
        self.assertEqual(profile.native_context_management, "unknown")
        self.assertEqual(profile.streaming, "unknown")

    def test_near_match_and_model_name_do_not_inherit_profile(self):
        bundle = build_gemini_conformance()
        near_matches = (
            CapabilityKey(
                "generic-google",
                "gemini_generate_content",
                "google",
                model_family="gemini-future",
            ),
            CapabilityKey("generic-google", "gemini_generate_content", "google-v2"),
            CapabilityKey("gemini-cli", "gemini_generate_content", "google"),
        )
        for key in near_matches:
            detected = bundle.detector.detect(key)
            self.assertIsNone(detected.profile)
            self.assertEqual(detected.compatibility.state, CompatibilityState.PASSTHROUGH_ONLY)
            self.assertEqual(detected.compatibility.reason, "unknown_capability")


class GeminiConformanceCasesTests(unittest.TestCase):
    def test_conformance_cases_are_deterministic_and_green(self):
        cases = gemini_conformance_cases()
        self.assertEqual(
            tuple(sorted(cases)),
            (
                "cached_content_reference_preserved",
                "certification_state_passthrough_only",
                "function_response_exact_passthrough",
                "malformed_function_passthrough",
                "near_match_non_inheritance",
                "roleless_text_roundtrip",
                "streaming_unclaimed",
                "supported_roundtrip",
                "system_instruction_text_mutation",
                "text_path_mutation_preserves_protocol",
                "thought_signature_exact_passthrough",
                "tool_classification",
                "unknown_multimodal_passthrough",
                "unsupported_tool_passthrough",
            ),
        )
        self.assertTrue(all(case() is True for case in cases.values()))
        results = run_gemini_conformance()
        self.assertEqual(tuple(result.name for result in results), tuple(sorted(cases)))
        self.assertTrue(all(result.passed for result in results))


if __name__ == "__main__":
    unittest.main()
