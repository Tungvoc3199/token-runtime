import unittest
from dataclasses import FrozenInstanceError

from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import (
    CompatibilityRecord,
    CompatibilityRegistry,
    CompatibilityState,
    DuplicateCompatibilityError,
)


class CompatibilityTests(unittest.TestCase):
    def test_unknown_lookup_is_total_and_passthrough_only(self):
        key = CapabilityKey("codex", "responses", "openai")
        unknown = CompatibilityRegistry().get(key)
        self.assertEqual(unknown.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(unknown.evidence_id, "unknown")
        self.assertEqual(unknown.reason, "unknown_capability")

    def test_registration_is_idempotent_and_conflicts_fail_closed(self):
        key = CapabilityKey("codex", "responses", "openai")
        record = CompatibilityRecord(key, CompatibilityState.CANARY, "fixture-v1")
        registry = CompatibilityRegistry()
        self.assertIs(registry.register(record), record)
        self.assertIs(registry.register(record), record)
        conflict = CompatibilityRecord(
            key,
            CompatibilityState.BLOCKED,
            "fixture-v2",
            "conflict",
        )
        with self.assertRaises(DuplicateCompatibilityError):
            registry.register(conflict)

    def test_matrix_is_sorted_immutable_snapshot(self):
        registry = CompatibilityRegistry()
        later = CompatibilityRecord(
            CapabilityKey("z-client", "responses", "provider"),
            CompatibilityState.EXPERIMENTAL,
            "z",
        )
        earlier = CompatibilityRecord(
            CapabilityKey("a-client", "responses", "provider"),
            CompatibilityState.CERTIFIED,
            "a",
        )
        registry.register(later)
        registry.register(earlier)
        matrix = registry.matrix()
        registry.register(
            CompatibilityRecord(
                CapabilityKey("m-client", "responses", "provider"),
                CompatibilityState.CANARY,
                "m",
            )
        )
        self.assertEqual(matrix.records, (earlier, later))
        self.assertIs(matrix.get(earlier.key), earlier)
        with self.assertRaises(FrozenInstanceError):
            matrix.records = ()

    def test_state_values_are_exact_machine_readable_contract(self):
        self.assertEqual(
            {state.value for state in CompatibilityState},
            {
                "CERTIFIED",
                "CANARY",
                "EXPERIMENTAL",
                "PASSTHROUGH_ONLY",
                "UNSUPPORTED",
                "BLOCKED",
            },
        )

    def test_record_rejects_invalid_state_at_construction(self):
        key = CapabilityKey("codex", "responses", "openai")
        with self.assertRaises(TypeError):
            CompatibilityRecord(key, "CANARY", "fixture-v1")


if __name__ == "__main__":
    unittest.main()
