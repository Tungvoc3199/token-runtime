import json
import unittest

from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import CompatibilityState
from token_runtime.openai_certification import CODEX_RESPONSES_KEY, build_openai_certification


class Codex01540RecertificationTests(unittest.TestCase):
    def test_exact_01540_request_boundary_is_version_scoped_and_certified(self):
        from token_runtime.codex_recertification import (
            CODEX_01540_RESPONSES_KEY,
            build_codex_01540_recertification,
        )

        bundle = build_codex_01540_recertification()
        self.assertEqual(CODEX_01540_RESPONSES_KEY.client_version, "0.154.0")
        self.assertIsNone(CODEX_01540_RESPONSES_KEY.model_family)
        self.assertEqual(bundle.record.key, CODEX_01540_RESPONSES_KEY)
        self.assertEqual(bundle.record.state, CompatibilityState.CERTIFIED)
        self.assertEqual(bundle.record.reason, "request_boundary_certified")
        self.assertEqual(bundle.evidence.version_scope, "codex-cli-0.154.0")
        self.assertIn("cached-token-response-byte-fidelity", bundle.evidence.assertion_ids)
        self.assertEqual(
            bundle.profile.to_primitive()["key"]["client_version"],
            "0.154.0",
        )

    def test_01540_does_not_inherit_01534_or_promote_near_versions(self):
        from token_runtime.codex_recertification import (
            CODEX_01540_RESPONSES_KEY,
            build_codex_01540_recertification,
        )

        legacy = build_openai_certification()
        self.assertEqual(CODEX_RESPONSES_KEY.client_version, "0.153.4")
        self.assertEqual(
            legacy.detector.detect(CODEX_RESPONSES_KEY).compatibility.state,
            CompatibilityState.CERTIFIED,
        )
        self.assertEqual(CODEX_01540_RESPONSES_KEY.client_version, "0.154.0")

        bundle = build_codex_01540_recertification()
        near = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            client_version="0.154.1",
        )
        detected = bundle.detector.detect(near)
        self.assertIsNone(detected.profile)
        self.assertEqual(detected.compatibility.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(detected.compatibility.reason, "unknown_capability")

    def test_native_state_areas_remain_passthrough_safe(self):
        from token_runtime.codex_recertification import build_codex_01540_recertification

        bundle = build_codex_01540_recertification()
        areas = {item.area: item for item in bundle.areas}
        self.assertEqual(
            {name for name, item in areas.items() if item.state is CompatibilityState.CERTIFIED},
            {
                "responses_request_fidelity",
                "responses_response_fidelity",
                "token_off_on_boundary",
                "resume_fork_continuity",
            },
        )
        for name in (
            "native_context_compaction",
            "authorization_across_compaction",
            "long_context_continuity",
            "dynamic_plugin_skill_refresh",
            "mcp_oauth_rejected_no_replay",
            "prompt_server_cache_semantics",
        ):
            self.assertEqual(areas[name].state, CompatibilityState.PASSTHROUGH_ONLY)
            self.assertTrue(areas[name].reason)

    def test_profile_does_not_claim_unobserved_native_or_cache_semantics(self):
        from token_runtime.codex_recertification import build_codex_01540_recertification

        profile = build_codex_01540_recertification().profile
        self.assertIs(profile.exact_byte_preservation, True)
        self.assertIs(profile.tool_calls, True)
        self.assertEqual(profile.reasoning_state, "opaque-preserved")
        self.assertEqual(profile.native_context_management, "unknown")
        self.assertEqual(profile.stateful_sessions, "unknown")
        self.assertEqual(profile.prompt_cache, "unknown")
        self.assertEqual(profile.server_cache, "unknown")

    def test_evidence_is_deterministic_and_public_safe(self):
        from token_runtime.codex_recertification import build_codex_01540_recertification

        bundle = build_codex_01540_recertification()
        encoded = json.dumps(bundle.to_primitive(), sort_keys=True, separators=(",", ":"))
        self.assertIn("codex-cli-0.154.0", encoded)
        for forbidden in ("/home/", "/tmp/", "bearer ", "sk-", "api_key", "dummy"):
            self.assertNotIn(forbidden, encoded.lower())


if __name__ == "__main__":
    unittest.main()
