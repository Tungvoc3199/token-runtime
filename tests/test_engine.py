import tempfile
import unittest
from pathlib import Path

from token_runtime.engine import OptimizationEngine
from token_runtime.model import ContextBlock, OptimizationDecision, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.reducers import RepeatedLineReducer
from token_runtime.store import RecoveryStore


def envelope(*blocks):
    return RequestEnvelope(blocks=tuple(blocks), opaque={"model": "test"})


class ExplodingReducer:
    def reduce(self, block, store, *, protected):
        raise RuntimeError("boom")


class EngineTests(unittest.TestCase):
    def make_engine(self, tmp, reducers=None):
        return OptimizationEngine(
            planner=ContextPlanner(),
            store=RecoveryStore(Path(tmp) / "recovery.db"),
            reducers=reducers or [RepeatedLineReducer()],
        )

    def test_eligible_repetition_reduces_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = "redundant diagnostic payload that is intentionally long"
            request = envelope(
                ContextBlock("r", "retrieved", "\n".join([line] * 20)),
                ContextBlock("u", "user", "summarize", turn_index=2),
            )
            result = self.make_engine(tmp).optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.OPTIMIZE)
            self.assertLess(result.after_estimated_tokens, result.before_estimated_tokens)
            self.assertEqual(result.changed_block_ids, ("r",))
            self.assertEqual(result.envelope.blocks[1], request.blocks[1])

    def test_no_beneficial_change_bypasses_with_original_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = envelope(ContextBlock("u", "user", "short request", turn_index=1))
            result = self.make_engine(tmp).optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.BYPASS)
            self.assertIs(result.envelope, request)
            self.assertIn("no_eligible_reduction", result.reasons)

    def test_active_competing_decisions_bypass_before_reducers(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = envelope(
                ContextBlock("a", "retrieved", "DECISION: old action", turn_index=3),
                ContextBlock("b", "tool_output", "DECISION: new action", turn_index=3),
                ContextBlock("u", "user", "continue", turn_index=3),
            )
            result = self.make_engine(tmp).optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.BYPASS)
            self.assertIs(result.envelope, request)
            self.assertIn("competing_active_decisions", result.reasons)

    def test_reducer_exception_returns_exact_original_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = envelope(
                ContextBlock("r", "retrieved", "background"),
                ContextBlock("u", "user", "continue", turn_index=2),
            )
            result = self.make_engine(tmp, reducers=[ExplodingReducer()]).optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.BYPASS)
            self.assertIs(result.envelope, request)
            self.assertEqual(result.changed_block_ids, ())
            self.assertEqual(result.recovery_refs, ())
            self.assertIn("fallback_internal_error", result.reasons)


if __name__ == "__main__":
    unittest.main()


class HistoricalExactDedupTests(unittest.TestCase):
    def test_exact_duplicate_old_retrieved_blocks_are_deduped_but_latest_stays_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "reference payload " + ("alpha beta gamma delta " * 30)
            request = envelope(
                ContextBlock("r0", "retrieved", text, turn_index=0),
                ContextBlock("r1", "retrieved", text, turn_index=1),
                ContextBlock("r2", "retrieved", text, turn_index=3),
                ContextBlock("u", "user", "continue", turn_index=3),
            )
            engine = OptimizationEngine(
                planner=ContextPlanner(),
                store=RecoveryStore(Path(tmp) / "recovery.db"),
                reducers=[],
            )
            result = engine.optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.OPTIMIZE)
            by_id = {block.id: block.text for block in result.envelope.blocks}
            self.assertIn("TOKEN_DUPLICATE_OF:r2", by_id["r0"])
            self.assertIn("TOKEN_DUPLICATE_OF:r2", by_id["r1"])
            self.assertEqual(by_id["r2"], text)
            self.assertLess(len(by_id["r0"]), len(text))
            self.assertLess(len(by_id["r1"]), len(text))
            self.assertTrue(result.recovery_refs)
            self.assertEqual(engine.store.get(result.recovery_refs[-1]), text.encode())


class HistoricalToolOutputExactDedupTests(unittest.TestCase):
    def test_exact_duplicate_old_tool_outputs_are_deduped_but_latest_stays_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "tool evidence payload " + ("alpha beta gamma delta " * 30)
            request = envelope(
                ContextBlock("t0", "tool_output", text, turn_index=0),
                ContextBlock("t1", "tool_output", text, turn_index=1),
                ContextBlock("t2", "tool_output", text, turn_index=3),
                ContextBlock("u", "user", "continue", turn_index=3),
            )
            engine = OptimizationEngine(
                planner=ContextPlanner(),
                store=RecoveryStore(Path(tmp) / "recovery.db"),
                reducers=[],
            )
            result = engine.optimize(request)
            self.assertEqual(result.decision, OptimizationDecision.OPTIMIZE)
            by_id = {block.id: block.text for block in result.envelope.blocks}
            self.assertIn("TOKEN_DUPLICATE_OF:t2", by_id["t0"])
            self.assertIn("TOKEN_DUPLICATE_OF:t2", by_id["t1"])
            self.assertEqual(by_id["t2"], text)
            self.assertTrue(result.recovery_refs)
            self.assertEqual(engine.store.get(result.recovery_refs[-1]), text.encode())