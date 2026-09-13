import unittest
from dataclasses import FrozenInstanceError

from token_runtime.capabilities import (
    CapabilityKey,
    CapabilityProfile,
    CapabilityRegistry,
    DuplicateCapabilityError,
)


class CapabilityTests(unittest.TestCase):
    def test_profile_is_immutable_and_serializes_to_primitives(self):
        key = CapabilityKey("codex", "responses", "openai", "opaque-family")
        profile = CapabilityProfile(
            key=key,
            exact_byte_preservation=True,
            evidence_id="fixture-v1",
        )
        with self.assertRaises(FrozenInstanceError):
            profile.evidence_id = "changed"
        primitive = profile.to_primitive()
        self.assertEqual(primitive["key"]["client_family"], "codex")
        self.assertEqual(primitive["key"]["model_family"], "opaque-family")
        self.assertIs(primitive["exact_byte_preservation"], True)
        self.assertNotIn("client_version", primitive["key"])

    def test_versioned_key_serializes_exact_client_version(self):
        key = CapabilityKey("codex", "responses", "openai", client_version="0.154.0")
        profile = CapabilityProfile(key=key, evidence_id="fixture-v2")
        self.assertEqual(profile.to_primitive()["key"]["client_version"], "0.154.0")

    def test_snapshot_sorts_unversioned_and_versioned_same_boundary(self):
        registry = CapabilityRegistry()
        unversioned = CapabilityProfile(
            key=CapabilityKey("codex", "responses", "openai"), evidence_id="legacy"
        )
        versioned = CapabilityProfile(
            key=CapabilityKey("codex", "responses", "openai", client_version="0.154.0"),
            evidence_id="versioned",
        )
        registry.register(versioned)
        registry.register(unversioned)
        self.assertEqual(registry.snapshot(), (unversioned, versioned))

    def test_registration_is_idempotent_for_equal_value_and_rejects_conflict(self):
        key = CapabilityKey("codex", "responses", "openai", "opaque-family")
        profile = CapabilityProfile(
            key=key,
            exact_byte_preservation=True,
            evidence_id="fixture-v1",
        )
        registry = CapabilityRegistry()
        self.assertIs(registry.register(profile), profile)
        self.assertIs(registry.register(profile), profile)
        conflict = CapabilityProfile(
            key=key,
            exact_byte_preservation=False,
            evidence_id="fixture-v2",
        )
        with self.assertRaises(DuplicateCapabilityError):
            registry.register(conflict)

    def test_snapshot_is_sorted_by_opaque_key_without_inference(self):
        registry = CapabilityRegistry()
        later = CapabilityProfile(
            key=CapabilityKey("z-client", "responses", "provider", "gpt-special"),
            evidence_id="z",
        )
        earlier = CapabilityProfile(
            key=CapabilityKey("a-client", "responses", "provider", "not-gpt-special"),
            evidence_id="a",
        )
        registry.register(later)
        registry.register(earlier)
        self.assertEqual(registry.snapshot(), (earlier, later))
        self.assertIs(registry.get(earlier.key), earlier)
        self.assertIsNone(
            registry.get(CapabilityKey("a-client", "responses", "provider", "gpt-special"))
        )


if __name__ == "__main__":
    unittest.main()


class CapabilityDetectorTests(unittest.TestCase):
    def test_detector_uses_exact_key_and_unknown_defaults_passthrough(self):
        from token_runtime.capabilities import CapabilityDetector
        from token_runtime.compatibility import (
            CompatibilityRecord,
            CompatibilityRegistry,
            CompatibilityState,
        )

        exact = CapabilityKey("codex", "responses", "openai", "opaque-family")
        capabilities = CapabilityRegistry()
        profile = CapabilityProfile(key=exact, evidence_id="fixture-v1")
        capabilities.register(profile)
        compatibility = CompatibilityRegistry()
        record = CompatibilityRecord(exact, CompatibilityState.CERTIFIED, "fixture-v1")
        compatibility.register(record)
        detector = CapabilityDetector(capabilities, compatibility)

        detected = detector.detect(exact)
        self.assertIs(detected.profile, profile)
        self.assertIs(detected.compatibility, record)

        near_match = CapabilityKey("codex", "responses", "openai", "opaque-family-v2")
        unknown = detector.detect(near_match)
        self.assertIsNone(unknown.profile)
        self.assertEqual(
            unknown.compatibility.state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )
        self.assertEqual(unknown.compatibility.reason, "unknown_capability")
