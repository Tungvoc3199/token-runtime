import unittest

from token_runtime.capabilities import (
    CapabilityDetector,
    CapabilityKey,
    CapabilityProfile,
    CapabilityRegistry,
    DuplicateCapabilityError,
)
from token_runtime.compatibility import CompatibilityRegistry, CompatibilityState
from token_runtime.conformance import (
    ConformanceFailure,
    require_conformance,
    run_conformance,
)
from token_runtime.feature_flags import FeatureEffect, FeatureFlagState, permitted_effect


class ConformanceTests(unittest.TestCase):
    def test_results_are_sorted_independent_of_mapping_order(self):
        cases = {
            "unknown_passthrough": lambda: True,
            "matrix_sorted": lambda: True,
        }
        results = run_conformance(dict(reversed(tuple(cases.items()))))
        self.assertEqual(
            tuple(result.name for result in results),
            ("matrix_sorted", "unknown_passthrough"),
        )
        self.assertTrue(all(result.passed for result in results))

    def test_exception_is_captured_without_traceback_and_require_fails_sorted(self):
        def explode():
            raise ValueError("fixture")

        results = run_conformance({"z_fail": explode, "a_false": lambda: False})
        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["z_fail"].passed)
        self.assertIn("ValueError", by_name["z_fail"].detail)
        self.assertNotIn("Traceback", by_name["z_fail"].detail)
        with self.assertRaisesRegex(ConformanceFailure, "a_false, z_fail"):
            require_conformance(results)

    def test_foundation_invariants_compose_as_conformance_cases(self):
        key = CapabilityKey("codex", "responses", "openai", "opaque")
        capabilities = CapabilityRegistry()
        profile = CapabilityProfile(key=key, evidence_id="fixture-v1")
        capabilities.register(profile)
        compatibility = CompatibilityRegistry()
        detector = CapabilityDetector(capabilities, compatibility)

        def duplicate_conflict_fails_closed():
            try:
                capabilities.register(
                    CapabilityProfile(key=key, evidence_id="fixture-v2")
                )
            except DuplicateCapabilityError:
                return True
            return False

        cases = {
            "idempotent_registration": lambda: capabilities.register(profile) is profile,
            "matrix_sorted": lambda: compatibility.matrix().records == (),
            "passthrough_never_executes": lambda: permitted_effect(
                FeatureFlagState.ENABLED,
                CompatibilityState.PASSTHROUGH_ONLY,
            )
            is FeatureEffect.OBSERVE,
            "unknown_passthrough": lambda: detector.detect(
                CapabilityKey("other", "responses", "openai", "opaque")
            ).compatibility.state
            is CompatibilityState.PASSTHROUGH_ONLY,
            "duplicate_conflict_fails_closed": duplicate_conflict_fails_closed,
        }
        results = run_conformance(cases)
        require_conformance(results)
        self.assertTrue(all(result.passed for result in results))


if __name__ == "__main__":
    unittest.main()
