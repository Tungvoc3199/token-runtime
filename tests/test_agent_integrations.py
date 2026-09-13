import importlib.util
import unittest

from token_runtime.capabilities import (
    CapabilityDetector,
    CapabilityKey,
    CapabilityRegistry,
)
from token_runtime.codex_recertification import (
    CODEX_01540_RESPONSES_KEY,
    build_codex_01540_recertification,
)
from token_runtime.compatibility import CompatibilityRegistry, CompatibilityState
from token_runtime.feature_flags import FeatureEffect, FeatureFlagState
import token_runtime.agent_integrations as agent_integrations
import token_runtime.contracts as contracts


class AgentView:
    agent_id = "fixture-agent"
    capability_key = CapabilityKey("fixture", "responses", "fixture-provider")
    endpoint = "/v1/responses"


class AgentIntegrationContractTests(unittest.TestCase):
    def test_agent_contract_is_structural_and_thin(self):
        self.assertTrue(hasattr(contracts, "AgentIntegrationContract"))
        contract = getattr(contracts, "AgentIntegrationContract")
        self.assertIsInstance(AgentView(), contract)
        self.assertFalse(hasattr(AgentView(), "optimize"))
        self.assertFalse(hasattr(AgentView(), "prepare"))

    def test_agent_integration_module_exists(self):
        self.assertIsNotNone(
            importlib.util.find_spec("token_runtime.agent_integrations")
        )

    def test_unknown_agent_resolves_passthrough_via_existing_capability_policy(self):
        framework = agent_integrations.AgentIntegrationFramework(
            CapabilityDetector(CapabilityRegistry(), CompatibilityRegistry()),
            flag_state=FeatureFlagState.ENABLED,
        )
        decision = framework.resolve(AgentView())
        self.assertEqual(
            decision.compatibility_state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )
        self.assertEqual(decision.effect, FeatureEffect.OBSERVE)
        self.assertEqual(decision.mode.value, "PASSTHROUGH")
        self.assertEqual(decision.reason, "unknown_capability")

    def test_codex_01540_reference_reuses_existing_certification(self):
        self.assertTrue(
            hasattr(agent_integrations, "codex_01540_reference"),
            "C4.5 requires the Codex 0.154.0 reference descriptor",
        )
        reference = agent_integrations.codex_01540_reference()
        existing = build_codex_01540_recertification()
        self.assertIs(reference.capability_key, CODEX_01540_RESPONSES_KEY)
        self.assertEqual(reference.agent_id, "codex")
        self.assertEqual(reference.endpoint, "/v1/responses")
        self.assertEqual(existing.record.key, reference.capability_key)

    def test_future_codex_version_and_model_name_do_not_inherit_certification(self):
        self.assertTrue(
            hasattr(agent_integrations, "build_codex_01540_agent_framework"),
            "C4.5 requires a framework bound to existing Codex evidence",
        )
        framework = agent_integrations.build_codex_01540_agent_framework()
        keys = (
            CapabilityKey(
                "codex", "responses", "openai-compatible", client_version="0.154.1"
            ),
            CapabilityKey(
                "codex",
                "responses",
                "openai-compatible",
                model_family="gpt-5.6-sol",
                client_version="0.154.0",
            ),
        )
        for key in keys:
            candidate = type(
                "Candidate",
                (),
                {"agent_id": "codex", "capability_key": key, "endpoint": "/v1/responses"},
            )()
            decision = framework.resolve(candidate)
            self.assertEqual(
                decision.compatibility_state,
                CompatibilityState.PASSTHROUGH_ONLY,
            )
            self.assertEqual(decision.mode.value, "PASSTHROUGH")
            self.assertEqual(decision.reason, "unknown_capability")

    def test_exact_codex_reference_resolves_token_without_copied_evidence(self):
        self.assertTrue(
            hasattr(agent_integrations, "build_codex_01540_agent_framework")
        )
        framework = agent_integrations.build_codex_01540_agent_framework()
        reference = agent_integrations.codex_01540_reference()
        decision = framework.resolve(reference)
        existing = build_codex_01540_recertification()
        self.assertEqual(decision.compatibility_state, CompatibilityState.CERTIFIED)
        self.assertEqual(decision.effect, FeatureEffect.EXECUTE)
        self.assertEqual(decision.mode.value, "TOKEN")
        self.assertEqual(decision.evidence_id, existing.record.evidence_id)
        self.assertEqual(decision.reason, existing.record.reason)


if __name__ == "__main__":
    unittest.main()
