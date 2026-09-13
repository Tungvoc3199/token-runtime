import unittest

from token_runtime.agent_integrations import AgentIntegrationFramework
from token_runtime.capabilities import (
    CapabilityDetector,
    CapabilityKey,
    CapabilityProfile,
    CapabilityRegistry,
)
from token_runtime.compatibility import (
    CompatibilityRecord,
    CompatibilityRegistry,
    CompatibilityState,
)
from token_runtime.feature_flags import FeatureEffect, FeatureFlagState


class CertifiedWithoutProfileAgent:
    agent_id = "fixture-agent"
    capability_key = CapabilityKey("fixture", "responses", "fixture-provider")
    endpoint = "/v1/responses"


class AgentIntegrationSafetyTests(unittest.TestCase):
    def test_certified_record_without_capability_profile_fails_to_passthrough(self):
        compatibility = CompatibilityRegistry()
        compatibility.register(
            CompatibilityRecord(
                CertifiedWithoutProfileAgent.capability_key,
                CompatibilityState.CERTIFIED,
                "fixture-evidence",
            )
        )
        framework = AgentIntegrationFramework(
            CapabilityDetector(CapabilityRegistry(), compatibility),
            flag_state=FeatureFlagState.ENABLED,
        )
        decision = framework.resolve(CertifiedWithoutProfileAgent())
        self.assertEqual(decision.mode.value, "PASSTHROUGH")
        self.assertEqual(decision.compatibility_state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(decision.effect, FeatureEffect.OBSERVE)
        self.assertEqual(decision.evidence_id, "unknown")
        self.assertEqual(decision.reason, "missing_capability_profile")


class _FixtureAgent:
    agent_id = "fixture-agent"
    endpoint = "/v1/responses"

    def __init__(self, key):
        self.capability_key = key


class AgentIntegrationPolicyTests(unittest.TestCase):
    def _decision(self, state, flag_state):
        key = CapabilityKey("fixture", "responses", "fixture-provider")
        capabilities = CapabilityRegistry()
        capabilities.register(CapabilityProfile(key=key, evidence_id="fixture-evidence"))
        compatibility = CompatibilityRegistry()
        compatibility.register(
            CompatibilityRecord(key, state, "fixture-evidence", "fixture")
        )
        framework = AgentIntegrationFramework(
            CapabilityDetector(capabilities, compatibility),
            flag_state=flag_state,
        )
        return framework.resolve(_FixtureAgent(key))

    def test_existing_feature_flag_policy_is_the_only_execution_policy(self):
        expected = {
            (CompatibilityState.CERTIFIED, FeatureFlagState.ENABLED): "TOKEN",
            (CompatibilityState.CANARY, FeatureFlagState.ENABLED): "PASSTHROUGH",
            (CompatibilityState.CANARY, FeatureFlagState.CANARY): "TOKEN",
            (CompatibilityState.EXPERIMENTAL, FeatureFlagState.ENABLED): "PASSTHROUGH",
            (CompatibilityState.PASSTHROUGH_ONLY, FeatureFlagState.ENABLED): "PASSTHROUGH",
            (CompatibilityState.UNSUPPORTED, FeatureFlagState.ENABLED): "PASSTHROUGH",
            (CompatibilityState.BLOCKED, FeatureFlagState.ENABLED): "PASSTHROUGH",
        }
        for (state, flag_state), mode in expected.items():
            with self.subTest(state=state, flag_state=flag_state):
                decision = self._decision(state, flag_state)
                self.assertEqual(decision.mode.value, mode)

    def test_framework_exposes_no_optimizer_or_gateway_execution_api(self):
        framework = AgentIntegrationFramework(
            CapabilityDetector(CapabilityRegistry(), CompatibilityRegistry())
        )
        for name in ("optimize", "prepare", "forward", "install", "uninstall"):
            self.assertFalse(hasattr(framework, name), name)


class AgentIntegrationEvidenceTests(unittest.TestCase):
    def test_mismatched_profile_and_compatibility_evidence_fails_to_passthrough(self):
        key = CapabilityKey("fixture", "responses", "fixture-provider")
        capabilities = CapabilityRegistry()
        capabilities.register(CapabilityProfile(key=key, evidence_id="profile-evidence"))
        compatibility = CompatibilityRegistry()
        compatibility.register(
            CompatibilityRecord(
                key,
                CompatibilityState.CERTIFIED,
                "compatibility-evidence",
                "certified",
            )
        )
        framework = AgentIntegrationFramework(
            CapabilityDetector(capabilities, compatibility),
            flag_state=FeatureFlagState.ENABLED,
        )
        decision = framework.resolve(_FixtureAgent(key))
        self.assertEqual(decision.mode.value, "PASSTHROUGH")
        self.assertEqual(decision.compatibility_state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(decision.evidence_id, "unknown")
        self.assertEqual(decision.reason, "capability_evidence_mismatch")


if __name__ == "__main__":
    unittest.main()
