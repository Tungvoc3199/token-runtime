import unittest
from dataclasses import FrozenInstanceError

from token_runtime.compatibility import CompatibilityState
from token_runtime.anthropic_preserved_thinking_cert import (
    ANTHROPIC_PRESERVED_THINKING_KEY,
    BINDING_BETA,
    BINDING_MODE,
    AnthropicPreservedThinkingLiveEvidence,
    AnthropicPreservedThinkingOfflineEvidence,
    build_anthropic_preserved_thinking_generation,
    classify_anthropic_preserved_thinking,
)


class AnthropicPreservedThinkingEvidenceTests(unittest.TestCase):
    def test_exact_capability_key_does_not_use_model_wildcard(self):
        key = ANTHROPIC_PRESERVED_THINKING_KEY
        self.assertEqual(key.client_family, "generic-anthropic")
        self.assertEqual(key.protocol_family, "anthropic_messages")
        self.assertEqual(key.provider_family, "anthropic")
        self.assertEqual(key.model_family, "claude-fable-5-1")

    def test_offline_evidence_is_immutable_and_strictly_boolean(self):
        evidence = self._offline(True)
        self.assertTrue(evidence.complete)
        with self.assertRaises(FrozenInstanceError):
            evidence.inventory_complete = False
        with self.assertRaises(TypeError):
            AnthropicPreservedThinkingOfflineEvidence(
                evidence_id="bad-bool",
                inventory_complete=1,
                model_scope_exact=True,
                hard_bypass_complete=True,
                thinking_stripped_control_reducible=True,
                protected_prefix_exact=True,
                token_off_on_wire_equivalent=True,
                tool_history_fidelity=True,
                cache_metadata_preserved=True,
                resume_continuity=True,
                unknown_native_passthrough=True,
            )

    def test_live_evidence_requires_exact_binding_scope_and_finite_estimate(self):
        evidence = self._live(complete=True)
        self.assertTrue(evidence.complete)
        self.assertEqual(evidence.binding_beta, BINDING_BETA)
        self.assertEqual(evidence.prefix_mismatch_behavior, BINDING_MODE)
        self.assertEqual(evidence.accounting_status, "estimated_from_response_usage")
        for bad in ("NaN", "Infinity", "-0.01"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self._live(complete=True, estimated_cost_usd=bad)

    def test_benchmark_generation_is_deterministic_and_has_new_identity(self):
        first = build_anthropic_preserved_thinking_generation(("offline", "live"))
        second = build_anthropic_preserved_thinking_generation(("live", "offline", "offline"))
        self.assertEqual(first, second)
        self.assertEqual(first.generation_id, "token-anthropic-preserved-thinking-cert-1:pt-v1")
        self.assertEqual(first.evidence_ids, ("live", "offline"))

    def test_classification_never_exceeds_passthrough_only(self):
        incomplete = classify_anthropic_preserved_thinking(self._offline(False), None)
        offline = classify_anthropic_preserved_thinking(self._offline(True), None)
        live_bad = classify_anthropic_preserved_thinking(
            self._offline(True), self._live(complete=False)
        )
        live_good = classify_anthropic_preserved_thinking(
            self._offline(True), self._live(complete=True)
        )
        for record in (incomplete, offline, live_bad, live_good):
            self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(incomplete.reason, "offline_contract_incomplete")
        self.assertEqual(offline.reason, "offline_conformance_only")
        self.assertEqual(live_bad.reason, "live_contract_incomplete")
        self.assertEqual(live_good.reason, "live_canary_candidate")

    def test_live_unknown_binding_or_boolean_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            self._live(complete=True, binding_beta="future-beta")
        with self.assertRaises(ValueError):
            self._live(complete=True, binding_mode="error")
        with self.assertRaises(TypeError):
            self._live(complete=True, usage_complete=1)

    @staticmethod
    def _offline(complete: bool) -> AnthropicPreservedThinkingOfflineEvidence:
        return AnthropicPreservedThinkingOfflineEvidence(
            evidence_id="offline-evidence",
            inventory_complete=complete,
            model_scope_exact=complete,
            hard_bypass_complete=complete,
            thinking_stripped_control_reducible=complete,
            protected_prefix_exact=True,
            token_off_on_wire_equivalent=True,
            tool_history_fidelity=True,
            cache_metadata_preserved=True,
            resume_continuity=True,
            unknown_native_passthrough=True,
        )

    @staticmethod
    def _live(
        *,
        complete: bool,
        estimated_cost_usd: str = "0.040000",
        binding_beta: str = BINDING_BETA,
        binding_mode: str = BINDING_MODE,
        usage_complete: bool = True,
    ) -> AnthropicPreservedThinkingLiveEvidence:
        return AnthropicPreservedThinkingLiveEvidence(
            evidence_id="live-evidence",
            model_id="claude-fable-5-1",
            binding_beta=binding_beta,
            prefix_mismatch_behavior=binding_mode,
            cache_hit_observed=complete,
            tool_history_fidelity=complete,
            resume_continuity=complete,
            prefix_binding_observed=complete,
            input_transformations_clear=complete,
            usage_complete=usage_complete if complete else False,
            estimated_cost_usd=estimated_cost_usd,
            accounting_status="estimated_from_response_usage",
        )


if __name__ == "__main__":
    unittest.main()
