import tempfile
import unittest
from pathlib import Path

import token_runtime.capabilities
import token_runtime.compatibility
import token_runtime.conformance
import token_runtime.contracts
import token_runtime.feature_flags
import token_runtime.strategies
from token_runtime.adapters import ChatCompletionsAdapter, ResponsesAdapter
from token_runtime.engine import OptimizationEngine
from token_runtime.model import ContextBlock, OptimizationDecision, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.reducers import RepeatedLineReducer
from token_runtime.store import RecoveryStore

EVOLUTION_MODULES = (
    token_runtime.capabilities,
    token_runtime.compatibility,
    token_runtime.conformance,
    token_runtime.contracts,
    token_runtime.feature_flags,
    token_runtime.strategies,
)


class EvolutionRuntimeIsolationTests(unittest.TestCase):
    def test_existing_response_and_chat_fixtures_round_trip_exactly(self):
        responses_payload = {
            "model": "vscode-debug",
            "instructions": "Keep exact constraints.",
            "input": [
                {"role": "assistant", "content": "old context"},
                {"role": "user", "content": [{"type": "input_text", "text": "current task"}]},
                {"type": "function_call_output", "call_id": "c1", "output": "tool result"},
            ],
            "reasoning": {"effort": "medium"},
        }
        responses = ResponsesAdapter()
        self.assertEqual(
            responses.serialize(responses.parse(responses_payload)),
            responses_payload,
        )

        chat_payload = {
            "model": "gpt-test",
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "assistant", "content": "old answer"},
                {"role": "tool", "tool_call_id": "c1", "content": "ERROR timeout"},
                {"role": "user", "content": "continue"},
            ],
            "tools": [{"type": "function", "function": {"name": "query", "parameters": {}}}],
            "temperature": 0,
        }
        chat = ChatCompletionsAdapter()
        self.assertEqual(chat.serialize(chat.parse(chat_payload)), chat_payload)

    def test_engine_behavior_is_independent_of_evolution_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = OptimizationEngine(
                planner=ContextPlanner(),
                store=RecoveryStore(Path(tmp) / "recovery.db"),
                reducers=[RepeatedLineReducer()],
            )
            line = "redundant diagnostic payload that is intentionally long"
            eligible = RequestEnvelope(
                blocks=(
                    ContextBlock("r", "retrieved", "\n".join([line] * 20)),
                    ContextBlock("u", "user", "summarize", turn_index=2),
                ),
                opaque={"model": "fixture"},
            )
            optimized = engine.optimize(eligible)
            self.assertEqual(optimized.decision, OptimizationDecision.OPTIMIZE)
            self.assertEqual(optimized.changed_block_ids, ("r",))

            short = RequestEnvelope(
                blocks=(ContextBlock("u", "user", "short request", turn_index=1),),
                opaque={"model": "fixture"},
            )
            bypassed = engine.optimize(short)
            self.assertEqual(bypassed.decision, OptimizationDecision.BYPASS)
            self.assertIs(bypassed.envelope, short)
            self.assertIn("no_eligible_reduction", bypassed.reasons)


if __name__ == "__main__":
    unittest.main()
