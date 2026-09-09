import tempfile
import unittest
from pathlib import Path

from token_runtime.benchmark import BenchmarkCase, benchmark_cases
from token_runtime.engine import OptimizationEngine
from token_runtime.model import ContextBlock, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


def make_engine(tmp):
    return OptimizationEngine(
        planner=ContextPlanner(),
        store=RecoveryStore(Path(tmp) / "recovery.db"),
    )


class BenchmarkTests(unittest.TestCase):
    def test_phase0c_shape_preserves_active_turn_while_reducing_old_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repeated = "old retrieved context with enough repeated bytes to reduce"
            envelope = RequestEnvelope(blocks=(
                ContextBlock("old", "assistant", "\n".join([repeated] * 40), turn_index=0),
                ContextBlock("system", "system", "DECISION: always re-read latest", turn_index=4),
                ContextBlock("tools", "tool_schema", "DECISION: tools query and act are available", turn_index=4),
                ContextBlock("obs", "tool_output", "DECISION: validate tenant_id", turn_index=4),
                ContextBlock("doc", "retrieved", "current support evidence", turn_index=4),
                ContextBlock("user", "user", "diagnose", turn_index=4),
            ))
            report = benchmark_cases([
                BenchmarkCase("phase0c-salience", envelope)
            ], make_engine(tmp))
            case = report.cases[0]
            self.assertEqual(case.decision, "optimize")
            self.assertGreater(case.saved_pct, 0.0)
            self.assertEqual(case.protected_byte_fidelity, 1.0)
            self.assertTrue(case.recoverable)

    def test_safe_redundancy_reduces_and_recovery_refs_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            repeated = "old assistant history line with enough bytes to reduce"
            envelope = RequestEnvelope(blocks=(
                ContextBlock("old", "assistant", "\n".join([repeated] * 40)),
                ContextBlock("user", "user", "current task", turn_index=1),
            ))
            report = benchmark_cases([
                BenchmarkCase("redundancy", envelope)
            ], make_engine(tmp))
            case = report.cases[0]
            self.assertEqual(case.decision, "optimize")
            self.assertGreater(case.saved_pct, 0.0)
            self.assertEqual(case.protected_byte_fidelity, 1.0)
            self.assertTrue(case.recoverable)
            self.assertGreater(report.total_saved_pct, 0.0)
            self.assertEqual(report.bypass_count, 0)

    def test_aggregate_counts_bypass_and_optimized_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            repeated = "redundant old context line with enough payload bytes"
            safe = RequestEnvelope(blocks=(
                ContextBlock("old", "assistant", "\n".join([repeated] * 30)),
                ContextBlock("u", "user", "task", turn_index=1),
            ))
            risky = RequestEnvelope(blocks=(
                ContextBlock("a", "retrieved", "DECISION: A", turn_index=1),
                ContextBlock("b", "tool_output", "DECISION: B", turn_index=1),
                ContextBlock("u2", "user", "task", turn_index=1),
            ))
            report = benchmark_cases([
                BenchmarkCase("safe", safe), BenchmarkCase("risky", risky)
            ], make_engine(tmp))
            self.assertEqual(report.optimized_count, 1)
            self.assertEqual(report.bypass_count, 1)
            self.assertIn("competing_active_decisions", report.cases[1].reasons)
            self.assertGreater(
                report.baseline_estimated_tokens,
                report.optimized_estimated_tokens,
            )


if __name__ == "__main__":
    unittest.main()
