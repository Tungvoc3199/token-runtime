import json
import tempfile
import unittest
from pathlib import Path

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
from token_runtime.engine import OptimizationEngine
from token_runtime.gateway import GatewayCore
from token_runtime.metrics import MetricsStore
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


MODEL_IDS = (
    "gpt-future",
    "claude-future",
    "gemini-future",
    "unknown-future-model",
)


def _make_core(tmp: str) -> GatewayCore:
    return GatewayCore(
        engine=OptimizationEngine(
            planner=ContextPlanner(),
            store=RecoveryStore(Path(tmp) / "recovery.db"),
        ),
        metrics=MetricsStore(Path(tmp) / "metrics.db"),
    )


class LlmChangeIsolationTests(unittest.TestCase):
    def test_future_model_identifiers_do_not_change_core_optimization_semantics(self):
        line = "redundant assistant history line with enough bytes to matter"
        optimized_messages = []

        for model_id in MODEL_IDS:
            with self.subTest(model_id=model_id), tempfile.TemporaryDirectory() as tmp:
                payload = {
                    "model": model_id,
                    "messages": [
                        {"role": "assistant", "content": "\n".join([line] * 20)},
                        {"role": "user", "content": "current task"},
                    ],
                }
                prepared = _make_core(tmp).prepare(
                    "/v1/chat/completions", json.dumps(payload).encode()
                )
                self.assertTrue(prepared.optimized)
                self.assertEqual(prepared.adapter, "chat_completions")
                changed = json.loads(prepared.body)
                self.assertEqual(changed["model"], model_id)
                optimized_messages.append(changed["messages"])

        self.assertTrue(optimized_messages)
        for messages in optimized_messages[1:]:
            self.assertEqual(messages, optimized_messages[0])

    def test_near_model_or_client_version_does_not_inherit_certification(self):
        exact = CapabilityKey(
            "codex",
            "responses",
            "openai",
            "gpt-certified",
            client_version="1.0.0",
        )
        capabilities = CapabilityRegistry()
        compatibility = CompatibilityRegistry()
        capabilities.register(
            CapabilityProfile(key=exact, evidence_id="evidence-exact")
        )
        compatibility.register(
            CompatibilityRecord(
                key=exact,
                state=CompatibilityState.CERTIFIED,
                evidence_id="evidence-exact",
            )
        )
        detector = CapabilityDetector(capabilities, compatibility)

        exact_detection = detector.detect(exact)
        self.assertIsNotNone(exact_detection.profile)
        self.assertEqual(
            exact_detection.compatibility.state, CompatibilityState.CERTIFIED
        )

        near_keys = (
            CapabilityKey(
                "codex",
                "responses",
                "openai",
                "gpt-certified-v2",
                client_version="1.0.0",
            ),
            CapabilityKey(
                "codex",
                "responses",
                "openai",
                "gpt-certified",
                client_version="1.0.1",
            ),
        )
        for near_key in near_keys:
            with self.subTest(key=near_key):
                detection = detector.detect(near_key)
                self.assertIsNone(detection.profile)
                self.assertEqual(
                    detection.compatibility.state,
                    CompatibilityState.PASSTHROUGH_ONLY,
                )
                self.assertEqual(
                    detection.compatibility.reason,
                    "unknown_capability",
                )


if __name__ == "__main__":
    unittest.main()
