import unittest

from token_runtime.compatibility import CompatibilityState
from token_runtime.feature_flags import (
    DuplicateFeatureFlagError,
    FeatureEffect,
    FeatureFlag,
    FeatureFlagRegistry,
    FeatureFlagState,
    permitted_effect,
)


class FeatureFlagTests(unittest.TestCase):
    def test_complete_flag_compatibility_truth_table(self):
        blocked = {CompatibilityState.BLOCKED, CompatibilityState.UNSUPPORTED}
        expected = {}
        for state in CompatibilityState:
            expected[(FeatureFlagState.DISABLED, state)] = FeatureEffect.NONE
            expected[(FeatureFlagState.SHADOW, state)] = (
                FeatureEffect.NONE if state in blocked else FeatureEffect.OBSERVE
            )
            expected[(FeatureFlagState.CANARY, state)] = (
                FeatureEffect.NONE
                if state in blocked
                else FeatureEffect.EXECUTE
                if state in {CompatibilityState.CANARY, CompatibilityState.CERTIFIED}
                else FeatureEffect.OBSERVE
            )
            expected[(FeatureFlagState.ENABLED, state)] = (
                FeatureEffect.NONE
                if state in blocked
                else FeatureEffect.EXECUTE
                if state is CompatibilityState.CERTIFIED
                else FeatureEffect.OBSERVE
            )

        actual = {
            (flag, state): permitted_effect(flag, state)
            for flag in FeatureFlagState
            for state in CompatibilityState
        }
        self.assertEqual(actual, expected)

    def test_unknown_flag_defaults_disabled(self):
        flag = FeatureFlagRegistry().get("missing")
        self.assertEqual(flag, FeatureFlag("missing", FeatureFlagState.DISABLED))

    def test_registration_is_idempotent_and_conflicts_fail_closed(self):
        registry = FeatureFlagRegistry()
        flag = FeatureFlag("evolution", FeatureFlagState.SHADOW)
        self.assertIs(registry.register(flag), flag)
        self.assertIs(registry.register(flag), flag)
        with self.assertRaises(DuplicateFeatureFlagError):
            registry.register(FeatureFlag("evolution", FeatureFlagState.ENABLED))

    def test_flag_rejects_invalid_state_at_construction(self):
        with self.assertRaises(TypeError):
            FeatureFlag("evolution", "shadow")


if __name__ == "__main__":
    unittest.main()
