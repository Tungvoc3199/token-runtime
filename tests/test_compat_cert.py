import unittest
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json

from token_runtime.capabilities import CapabilityKey
from token_runtime.compatibility import CompatibilityState
from token_runtime.compat_cert import (
    BenchmarkGeneration,
    CertificationEntry,
    CertificationMatrix,
    CertificationScope,
    CertificationTarget,
    CompatibilityPolicy,
    OSFamily,
    OSScopeKind,
    UpgradeDimension,
    UpgradeImpact,
    UpgradeSignal,
    build_current_certification,
)


class BenchmarkGenerationTests(unittest.TestCase):
    def test_generation_is_immutable_and_serializes_all_identity_dimensions(self):
        evidence_ids = ("evidence-a",)
        digest = sha256(
            json.dumps(sorted(evidence_ids), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        generation = BenchmarkGeneration(
            generation_id="compat-v1",
            schema_version=1,
            corpus_version="corpus-v1",
            evaluator_version="eval-v1",
            policy_version="policy-v1",
            evidence_digest=digest,
            evidence_ids=evidence_ids,
        )
        with self.assertRaises(FrozenInstanceError):
            generation.generation_id = "changed"
        self.assertEqual(
            generation.to_primitive(),
            {
                "generation_id": "compat-v1",
                "schema_version": 1,
                "corpus_version": "corpus-v1",
                "evaluator_version": "eval-v1",
                "policy_version": "policy-v1",
                "evidence_digest": digest,
                "evidence_ids": ["evidence-a"],
            },
        )

    def test_generation_rejects_digest_that_does_not_match_covered_evidence(self):
        with self.assertRaises(ValueError):
            BenchmarkGeneration(
                generation_id="compat-v1",
                schema_version=1,
                corpus_version="corpus-v1",
                evaluator_version="eval-v1",
                policy_version="policy-v1",
                evidence_digest="0" * 64,
                evidence_ids=("evidence-a",),
            )


class CertificationScopeTests(unittest.TestCase):
    def setUp(self):
        self.target = CertificationTarget(
            "codex",
            "responses",
            "openai-compatible",
        )

    def test_tested_version_set_matches_only_explicit_versions_and_os_values(self):
        scope = CertificationScope(
            target=self.target,
            client_versions=("0.154.0", "0.154.2"),
            os_scope=OSScopeKind.TESTED_SET,
            os_families=(OSFamily.LINUX, OSFamily.MACOS),
        )
        self.assertTrue(
            scope.matches(
                CapabilityKey(
                    "codex",
                    "responses",
                    "openai-compatible",
                    client_version="0.154.0",
                ),
                OSFamily.LINUX,
            )
        )
        self.assertFalse(
            scope.matches(
                CapabilityKey(
                    "codex",
                    "responses",
                    "openai-compatible",
                    client_version="0.154.1",
                ),
                OSFamily.LINUX,
            )
        )
        self.assertFalse(
            scope.matches(
                CapabilityKey(
                    "codex",
                    "responses",
                    "openai-compatible",
                    client_version="0.154.0",
                ),
                OSFamily.WINDOWS,
            )
        )

    def test_unversioned_scope_is_not_a_version_wildcard(self):
        scope = CertificationScope(
            target=CertificationTarget(
                "generic-openai",
                "responses",
                "openai-compatible",
            ),
            os_scope=OSScopeKind.OS_AGNOSTIC,
        )
        self.assertTrue(
            scope.matches(
                CapabilityKey(
                    "generic-openai",
                    "responses",
                    "openai-compatible",
                ),
                OSFamily.WINDOWS,
            )
        )
        self.assertFalse(
            scope.matches(
                CapabilityKey(
                    "generic-openai",
                    "responses",
                    "openai-compatible",
                    client_version="future",
                ),
                OSFamily.WINDOWS,
            )
        )

    def test_none_model_family_is_exact_not_a_model_wildcard(self):
        scope = CertificationScope(
            target=CertificationTarget(
                "generic-openai",
                "responses",
                "openai-compatible",
            ),
            os_scope=OSScopeKind.OS_AGNOSTIC,
        )
        self.assertFalse(
            scope.matches(
                CapabilityKey(
                    "generic-openai",
                    "responses",
                    "openai-compatible",
                    model_family="gpt-future",
                ),
                OSFamily.LINUX,
            )
        )

    def test_invalid_os_scope_shapes_fail_closed_at_construction(self):
        with self.assertRaises(ValueError):
            CertificationScope(
                target=self.target,
                os_scope=OSScopeKind.EXACT,
                os_families=(OSFamily.LINUX, OSFamily.WINDOWS),
            )
        with self.assertRaises(ValueError):
            CertificationScope(
                target=self.target,
                os_scope=OSScopeKind.TESTED_SET,
                os_families=(),
            )
        with self.assertRaises(ValueError):
            CertificationScope(
                target=self.target,
                os_scope=OSScopeKind.OS_AGNOSTIC,
                os_families=(OSFamily.LINUX,),
            )


class CompatibilityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.target = CertificationTarget(
            "codex",
            "responses",
            "openai-compatible",
       )
        self.key = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            client_version="0.154.0",
        )
        self.scope = CertificationScope(
            target=self.target,
            client_versions=("0.154.0",),
            os_scope=OSScopeKind.EXACT,
            os_families=(OSFamily.LINUX,),
        )
        covered = ("evidence-1",)
        digest = sha256(
            json.dumps(sorted(covered), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.generation = BenchmarkGeneration(
            generation_id="compat-v1",
            schema_version=1,
            corpus_version="corpus-v1",
            evaluator_version="eval-v1",
            policy_version="policy-v1",
            evidence_digest=digest,
            evidence_ids=covered,
        )

    def test_unknown_scope_defaults_to_passthrough_only(self):
        policy = CompatibilityPolicy((self.generation,))
        record = policy.resolve(
            CertificationMatrix(()),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.evidence_id, "unknown")
        self.assertEqual(record.reason, "unknown_capability")

    def test_certified_entry_requires_evidence_and_registered_generation(self):
        no_evidence = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CERTIFIED,
            evidence_ids=(),
            benchmark_generation_id="compat-v1",
            reason="fixture",
        )
        policy = CompatibilityPolicy((self.generation,))
        record = policy.resolve(
            CertificationMatrix((no_evidence,)),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "missing_certification_evidence")

        missing_generation = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CERTIFIED,
            evidence_ids=("evidence-1",),
            benchmark_generation_id="missing-generation",
            reason="fixture",
        )
        record = policy.resolve(
            CertificationMatrix((missing_generation,)),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "unknown_benchmark_generation")

    def test_certified_entry_rejects_blank_evidence_ids(self):
        for bad in ("", "   "):
            with self.subTest(evidence_id=bad):
                with self.assertRaises(ValueError):
                    CertificationEntry(
                        scope=self.scope,
                        state=CompatibilityState.CERTIFIED,
                        evidence_ids=(bad,),
                        benchmark_generation_id="compat-v1",
                        reason="fixture",
                    )

    def test_certified_entry_evidence_must_match_generation_digest(self):
        covered = ("evidence-covered",)
        digest = sha256(
            json.dumps(sorted(covered), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        generation = BenchmarkGeneration(
            generation_id="compat-v1",
            schema_version=1,
            corpus_version="corpus-v1",
            evaluator_version="eval-v1",
            policy_version="policy-v1",
            evidence_digest=digest,
            evidence_ids=covered,
        )
        entry = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CERTIFIED,
            evidence_ids=("different-evidence",),
            benchmark_generation_id="compat-v1",
            reason="fixture",
        )
        record = CompatibilityPolicy((generation,)).resolve(
            CertificationMatrix((entry,)),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "benchmark_evidence_mismatch")

    def test_required_benchmark_generation_mismatch_fails_closed(self):
        entry = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CERTIFIED,
            evidence_ids=("evidence-1",),
            benchmark_generation_id="compat-v1",
            reason="fixture",
        )
        policy = CompatibilityPolicy((self.generation,))
        record = policy.resolve(
            CertificationMatrix((entry,)),
            self.key,
            OSFamily.LINUX,
            required_benchmark_generation_id="compat-v2",
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "benchmark_generation_mismatch")

    def test_overlapping_scopes_fail_closed_instead_of_picking_a_row(self):
        entry_a = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CERTIFIED,
            evidence_ids=("evidence-a",),
            benchmark_generation_id="compat-v1",
            reason="fixture-a",
        )
        entry_b = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.CANARY,
            evidence_ids=("evidence-b",),
            reason="fixture-b",
        )
        policy = CompatibilityPolicy((self.generation,))
        record = policy.resolve(
            CertificationMatrix((entry_a, entry_b)),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "ambiguous_certification_scope")

    def test_non_certified_states_are_preserved_without_promotion(self):
        entry = CertificationEntry(
            scope=self.scope,
            state=CompatibilityState.PASSTHROUGH_ONLY,
            evidence_ids=("offline-only",),
            reason="offline_conformance_only",
        )
        record = CompatibilityPolicy(()).resolve(
            CertificationMatrix((entry,)),
            self.key,
            OSFamily.LINUX,
        )
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.evidence_id, "offline-only")
        self.assertEqual(record.reason, "offline_conformance_only")


class UpgradeRadarTests(unittest.TestCase):
    def test_upgrade_policy_distinguishes_review_targeted_full_and_block(self):
        policy = CompatibilityPolicy(())
        expected = {
            UpgradeDimension.CLIENT_UI: UpgradeImpact.REVIEW,
            UpgradeDimension.CLIENT_VERSION: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.SDK: UpgradeImpact.REVIEW,
            UpgradeDimension.TOKENIZER: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.CACHE_SEMANTICS: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.TOOL_SCHEMA: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.OS_RUNTIME: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.BENCHMARK_GENERATION: UpgradeImpact.TARGETED_RECERTIFY,
            UpgradeDimension.PROTOCOL_WIRE: UpgradeImpact.FULL_RECERTIFY,
            UpgradeDimension.SECURITY_CRITICAL: UpgradeImpact.BLOCK,
        }
        for dimension, impact in expected.items():
            with self.subTest(dimension=dimension):
                signal = UpgradeSignal(dimension, "before", "after")
                self.assertEqual(policy.classify_upgrade(signal), impact)

    def test_no_material_change_is_no_action(self):
        policy = CompatibilityPolicy(())
        signal = UpgradeSignal(UpgradeDimension.CLIENT_VERSION, "0.154.0", "0.154.0")
        self.assertEqual(policy.classify_upgrade(signal), UpgradeImpact.NO_ACTION)


class CurrentCertificationMatrixTests(unittest.TestCase):
    def test_current_matrix_preserves_known_states_and_exact_codex_versions(self):
        bundle = build_current_certification()

        codex_01534 = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            client_version="0.153.4",
        )
        codex_01540 = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            client_version="0.154.0",
       )
        codex_near = CapabilityKey(
            "codex",
            "responses",
            "openai-compatible",
            client_version="0.154.1",
       )

        self.assertEqual(
            bundle.resolve(codex_01534, OSFamily.LINUX).state,
            CompatibilityState.CERTIFIED,
        )
        self.assertEqual(
            bundle.resolve(codex_01540, OSFamily.LINUX).state,
            CompatibilityState.CERTIFIED,
        )
        self.assertEqual(
            bundle.resolve(codex_near, OSFamily.LINUX).state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )
        self.assertEqual(
            bundle.resolve(codex_01540, OSFamily.WINDOWS).state,
            CompatibilityState.PASSTHROUGH_ONLY,
        )

    def test_protocol_certification_can_be_explicitly_os_agnostic(self):
        bundle = build_current_certification()
        key = CapabilityKey(
            "generic-openai",
            "responses",
            "openai-compatible",
        )
        for os_family in OSFamily:
            with self.subTest(os_family=os_family):
                self.assertEqual(
                    bundle.resolve(key, os_family).state,
                    CompatibilityState.CERTIFIED,
                )

    def test_offline_anthropic_and_gemini_remain_passthrough_only(self):
        bundle = build_current_certification()
        keys = (
            CapabilityKey(
                "generic-anthropic",
                "anthropic_messages",
                "anthropic",
            ),
            CapabilityKey(
                "generic-google",
                "gemini_generate_content",
                "google",
            ),
        )
        for key in keys:
            with self.subTest(key=key):
                record = bundle.resolve(key, OSFamily.LINUX)
                self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
                self.assertEqual(record.reason, "offline_conformance_only")

    def test_current_matrix_does_not_infer_support_from_model_name(self):
        bundle = build_current_certification()
        key = CapabilityKey(
            "generic-openai",
            "responses",
            "openai-compatible",
            model_family="gpt-future",
        )
        record = bundle.resolve(key, OSFamily.LINUX)
        self.assertEqual(record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(record.reason, "unknown_capability")

    def test_current_bundle_is_deterministic_and_benchmark_bound(self):
        first = build_current_certification().to_primitive()
        second = build_current_certification().to_primitive()
        self.assertEqual(first, second)
        self.assertTrue(first["benchmark_generations"])
        certified = [
            row
            for row in first["matrix"]
            if row["state"] == CompatibilityState.CERTIFIED.value
        ]
        self.assertTrue(certified)
        self.assertTrue(all(row["benchmark_generation_id"] for row in certified))


if __name__ == "__main__":
    unittest.main()
