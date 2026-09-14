import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from token_runtime.agent_integrations import AgentIntegrationFramework, AgentIntegrationMode
from token_runtime.capabilities import CapabilityDetector, CapabilityKey, CapabilityRegistry
from token_runtime.compatibility import CompatibilityRegistry, CompatibilityState
from token_runtime.feature_flags import FeatureEffect, FeatureFlagState
from token_runtime.gateway import GatewayCore
from token_runtime.metrics import MetricsStore
from token_runtime.openai_agents_conformance import (
    ASSERTION_IDS,
    INPUT_EVENT_FIXTURES,
    OFFICIAL_SOURCE_REFS,
    OPENAI_AGENTS_API_KEY,
    RAW_CORPUS,
    SESSION_CREATE_FIXTURE,
    STREAM_EVENT_FRAMES,
    TESTED_SHAPE_MANIFEST,
    OpenAIAgentsConformanceBundle,
    build_openai_agents_conformance,
    corpus_digest,
    evidence_fingerprint,
    openai_agents_conformance_cases,
    run_openai_agents_conformance,
    tested_shape_fingerprint,
)
from token_runtime.protocol_registry import default_protocol_adapter_registry


class OpenAIAgentsBundleTests(unittest.TestCase):
    def test_exact_identity_and_passthrough_only(self):
        bundle = build_openai_agents_conformance()
        self.assertIsInstance(bundle, OpenAIAgentsConformanceBundle)
        self.assertEqual(
            OPENAI_AGENTS_API_KEY,
            CapabilityKey("generic-openai", "openai_agents_api", "openai"),
        )
        self.assertIsNone(bundle.profile.key.model_family)
        self.assertEqual(bundle.profile.key.client_version, "")
        self.assertIs(bundle.profile.stateful_sessions, True)
        self.assertIs(bundle.profile.native_context_management, True)
        self.assertEqual(bundle.profile.streaming, "unknown")
        self.assertEqual(bundle.profile.tool_calls, "unknown")
        self.assertEqual(bundle.record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(bundle.record.reason, "offline_conformance_only")
        self.assertEqual(bundle.profile.evidence_id, bundle.record.evidence_id)
        self.assertEqual(bundle.profile.evidence_id, bundle.evidence.evidence_id)


class OpenAIAgentsEvidenceTests(unittest.TestCase):
    def test_evidence_binds_shapes_corpus_assertions_and_snapshot(self):
        bundle = build_openai_agents_conformance()
        base = bundle.evidence.evidence_fingerprint

        changed_manifest = deepcopy(TESTED_SHAPE_MANIFEST)
        changed_manifest["stream_events"] = tuple(changed_manifest["stream_events"]) + (
            "AgentFutureEvent",
        )
        changed_shape = tested_shape_fingerprint(changed_manifest)
        self.assertNotEqual(changed_shape, bundle.evidence.tested_shape_fingerprint)
        self.assertNotEqual(
            evidence_fingerprint(
                tested_shape_fingerprint=changed_shape,
                corpus_digest=bundle.evidence.corpus_digest,
                assertion_ids=ASSERTION_IDS,
                snapshot_date=bundle.evidence.snapshot_date,
                official_source_refs=OFFICIAL_SOURCE_REFS,
                sdk_client_version=bundle.evidence.sdk_client_version,
            ),
            base,
        )

        changed_records = list(RAW_CORPUS)
        label, payload = changed_records[0]
        changed_records[0] = (label, payload + b" ")
        changed_corpus = corpus_digest(tuple(changed_records))
        self.assertNotEqual(changed_corpus, bundle.evidence.corpus_digest)
        self.assertNotEqual(
            evidence_fingerprint(
                tested_shape_fingerprint=bundle.evidence.tested_shape_fingerprint,
                corpus_digest=changed_corpus,
                assertion_ids=ASSERTION_IDS,
                snapshot_date=bundle.evidence.snapshot_date,
                official_source_refs=OFFICIAL_SOURCE_REFS,
                sdk_client_version=bundle.evidence.sdk_client_version,
            ),
            base,
        )

        for kwargs in (
            {"assertion_ids": ASSERTION_IDS + ("future_assertion",)},
            {"snapshot_date": "2026-09-14"},
            {"official_source_refs": OFFICIAL_SOURCE_REFS + ("https://example.invalid/future",)},
        ):
            params = {
                "tested_shape_fingerprint": bundle.evidence.tested_shape_fingerprint,
                "corpus_digest": bundle.evidence.corpus_digest,
                "assertion_ids": ASSERTION_IDS,
                "snapshot_date": bundle.evidence.snapshot_date,
                "official_source_refs": OFFICIAL_SOURCE_REFS,
                "sdk_client_version": bundle.evidence.sdk_client_version,
            }
            params.update(kwargs)
            self.assertNotEqual(evidence_fingerprint(**params), base)

    def test_corpus_digest_binds_order_duplicates_and_exact_bytes(self):
        records = RAW_CORPUS
        base = corpus_digest(records)
        swapped = list(records)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assertNotEqual(corpus_digest(tuple(swapped)), base)
        self.assertNotEqual(corpus_digest(records + (records[-1],)), base)
        label, payload = records[-1]
        changed = records[:-1] + ((label, payload + b" "),)
        self.assertNotEqual(corpus_digest(changed), base)


class OpenAIAgentsCorpusTests(unittest.TestCase):
    def test_session_fixture_covers_native_state_mcp_and_vaults(self):
        payload = json.loads(SESSION_CREATE_FIXTURE.decode("utf-8"))
        self.assertEqual(payload["environment"]["type"], "none")
        self.assertIn("agent_id", payload)
        self.assertIn("input", payload)
        self.assertIn("metadata", payload)
        self.assertIs(payload["stream"], True)
        self.assertEqual(payload["vault_ids"], ["vault_fixture"])
        self.assertTrue(payload["agent"]["multi_agent"]["enabled"])
        self.assertEqual(payload["agent"]["multi_agent"]["max_concurrent_subagents"], 2)
        self.assertTrue(any(tool.get("type") == "mcp" for tool in payload["agent"]["tools"]))
        self.assertEqual(payload["future_field"], {"opaque": True})

    def test_input_events_bind_idempotency_and_unknown_fields(self):
        by_label = dict(INPUT_EVENT_FIXTURES)
        message = json.loads(by_label["input-message"].decode("utf-8"))
        self.assertEqual(message["idempotency_key"], "idem_fixture_001")
        self.assertEqual(message["events"][0]["type"], "agent.session.input.message")
        self.assertIn("future_nested", message["events"][0])
        self.assertIn("input-cancellation", by_label)
        self.assertIn("input-tool-result", by_label)

    def test_stream_fixture_freezes_order_duplicates_and_unknown_event(self):
        raw_frames = tuple(payload for _, payload in STREAM_EVENT_FRAMES)
        labels = tuple(label for label, _ in STREAM_EVENT_FRAMES)
        self.assertGreaterEqual(len(raw_frames), 12)
        self.assertEqual(raw_frames.count(raw_frames[-2]), 2)
        self.assertEqual(labels[-2:], ("duplicate-frame", "duplicate-frame-copy"))
        parsed = [json.loads(frame.decode("utf-8")) for frame in raw_frames]
        self.assertTrue(any(item["type"] == "agent.session.future.event" for item in parsed))
        deltas = [item for item in parsed if item["type"].endswith("delta")]
        self.assertGreaterEqual(len(deltas), 3)
        self.assertTrue(all("event_id" in item for item in parsed if "future" not in item["type"]))

    def test_known_stream_fixture_types_match_frozen_official_snapshot(self):
        by_label = {
            label: json.loads(payload.decode("utf-8"))
            for label, payload in STREAM_EVENT_FRAMES
        }
        expected = {
            "session-created": "agent.session.created",
            "turn-created": "agent.session.turn.created",
            "environment-ready": "agent.session.environment.ready",
            "subagent-created": "agent.session.subagent.created",
            "item-added": "agent.session.turn.item.added",
            "content-part-added": "agent.session.turn.content_part.added",
            "output-text-delta-a": "agent.session.turn.output_text.delta",
            "output-text-delta-b": "agent.session.turn.output_text.delta",
            "reasoning-summary-delta": "agent.session.turn.reasoning_summary_text.delta",
            "command-output-delta": "agent.output.command_execution_output.delta",
            "requires-action": "agent.session.requires_action",
            "idle-error": "error",
            "duplicate-frame": "agent.session.idle",
            "duplicate-frame-copy": "agent.session.idle",
        }
        for label, event_type in expected.items():
            self.assertEqual(by_label[label]["type"], event_type, label)
        self.assertEqual(by_label["session-created"]["session"]["id"], "sess_fixture")
        self.assertEqual(
            by_label["subagent-created"]["subagent"]["session_id"],
            "sess_fixture",
        )
        self.assertEqual(by_label["command-output-delta"]["item_id"], "command_fixture")

    def test_official_sources_pin_generated_sdk_schema_snapshot(self):
        self.assertTrue(
            any(
                "openai/openai-python/tree/e12b81d3bbf644ec7045e152d69bc4b68d69cd48"
                in ref
                for ref in OFFICIAL_SOURCE_REFS
            )
        )


@dataclass(frozen=True, slots=True)
class _AgentsFixtureIntegration:
    agent_id: str = "openai-agents-fixture"
    capability_key: CapabilityKey = OPENAI_AGENTS_API_KEY
    endpoint: str = "/agents/sessions"


class OpenAIAgentsControlPlaneTests(unittest.TestCase):
    def test_enabled_flag_still_cannot_execute_token(self):
        bundle = build_openai_agents_conformance()
        decision = AgentIntegrationFramework(
            bundle.detector,
            flag_state=FeatureFlagState.ENABLED,
        ).resolve(_AgentsFixtureIntegration())
        self.assertEqual(decision.mode, AgentIntegrationMode.PASSTHROUGH)
        self.assertEqual(decision.effect, FeatureEffect.OBSERVE)
        self.assertEqual(decision.compatibility_state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(decision.reason, "offline_conformance_only")

    def test_near_keys_do_not_inherit(self):
        bundle = build_openai_agents_conformance()
        near = (
            CapabilityKey("generic-openai", "responses", "openai"),
            CapabilityKey("generic-openai", "chat_completions", "openai"),
            CapabilityKey("generic-openai", "openai_agents_api_v2", "openai"),
            CapabilityKey("generic-openai", "openai_agents_api", "openai-compatible"),
            CapabilityKey("generic-openai", "openai_agents_api", "openai", model_family="gpt-future"),
            CapabilityKey("generic-openai", "openai_agents_api", "openai", client_version="1"),
            CapabilityKey("codex", "openai_agents_api", "openai"),
        )
        for key in near:
            detected = bundle.detector.detect(key)
            self.assertIsNone(detected.profile)
            self.assertEqual(detected.compatibility.state, CompatibilityState.PASSTHROUGH_ONLY)
            self.assertEqual(detected.compatibility.reason, "unknown_capability")

    def test_conformance_cases_are_deterministic_and_green(self):
        cases = openai_agents_conformance_cases()
        self.assertEqual(tuple(sorted(cases)), ASSERTION_IDS)
        self.assertTrue(all(case() is True for case in cases.values()))
        results = run_openai_agents_conformance()
        self.assertEqual(tuple(item.name for item in results), ASSERTION_IDS)
        self.assertTrue(all(item.passed for item in results))

    def test_mismatched_evidence_fails_safe(self):
        bundle = build_openai_agents_conformance()
        capabilities = CapabilityRegistry()
        capabilities.register(bundle.profile)
        compatibility = CompatibilityRegistry()
        compatibility.register(
            replace(bundle.record, evidence_id=f"{bundle.record.evidence_id}:drift")
        )
        decision = AgentIntegrationFramework(
            CapabilityDetector(capabilities, compatibility),
            flag_state=FeatureFlagState.ENABLED,
        ).resolve(_AgentsFixtureIntegration())
        self.assertEqual(decision.mode, AgentIntegrationMode.PASSTHROUGH)
        self.assertEqual(decision.effect, FeatureEffect.OBSERVE)
        self.assertEqual(decision.compatibility_state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(decision.evidence_id, "unknown")
        self.assertEqual(decision.reason, "capability_evidence_mismatch")


class _NeverCalledEngine:
    def optimize(self, envelope):
        raise AssertionError("Agents paths must not reach the optimizer")


class OpenAIAgentsRoutingIsolationTests(unittest.TestCase):
    def test_default_registry_does_not_route_agents_paths(self):
        registry = default_protocol_adapter_registry()
        self.assertIsNone(registry.resolve("/agents/sessions"))
        self.assertIsNone(registry.resolve("/agents/sessions/session_fixture/events"))

    def test_gateway_post_prepare_is_exact_passthrough_for_agents_paths(self):
        raw = b'{  "events" : [{"type":"agent.session.input.message"}] }'
        with tempfile.TemporaryDirectory() as tmp:
            core = GatewayCore(
                engine=_NeverCalledEngine(),
                metrics=MetricsStore(Path(tmp) / "metrics.db"),
            )
            for path in (
                "/agents/sessions",
                "/agents/sessions/session_fixture/events",
            ):
                prepared = core.prepare(path, raw)
                self.assertIs(prepared.body, raw)
                self.assertFalse(prepared.optimized)
                self.assertEqual(prepared.reasons, ("unsupported_endpoint",))
                self.assertIsNone(prepared.adapter)


ROOT = Path(__file__).resolve().parents[1]


class OpenAIAgentsDocsContractTests(unittest.TestCase):
    def test_compatibility_docs_bound_agents_to_offline_passthrough(self):
        text = (ROOT / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("OpenAI Agents API", text)
        self.assertIn("PASSTHROUGH_ONLY", text)
        self.assertIn("offline", text.lower())
        self.assertIn("not routed", text.lower())
        self.assertNotIn("OpenAI Agents API | CERTIFIED", text)
        self.assertNotIn("OpenAI Agents API | CANARY", text)

    def test_llm_change_playbook_has_conformance_only_protocol_flow(self):
        text = (ROOT / "docs" / "LLM-CHANGE-PLAYBOOK.md").read_text(encoding="utf-8")
        self.assertIn("conformance-only", text.lower())
        self.assertIn("no adapter", text.lower())
        self.assertIn("no route", text.lower())
        self.assertIn("runtime support", text.lower())


if __name__ == "__main__":
    unittest.main()
