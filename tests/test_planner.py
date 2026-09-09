import unittest

from token_runtime.model import ContextBlock, OptimizationDecision, RequestEnvelope
from token_runtime.planner import ContextPlanner


def env(*blocks, wire_safe=True):
    return RequestEnvelope(blocks=tuple(blocks), wire_safe=wire_safe)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = ContextPlanner()

    def test_protects_system_current_user_and_latest_tool_output(self):
        request = env(
            ContextBlock("s", "system", "system rules", turn_index=0),
            ContextBlock("u0", "user", "old question", turn_index=0),
            ContextBlock("t0", "tool_output", "old output", turn_index=1),
            ContextBlock("u1", "user", "current question", turn_index=2),
            ContextBlock("t1", "tool_output", "latest evidence", turn_index=3),
            ContextBlock("r", "retrieved", "large reference", turn_index=2),
        )
        plan = self.planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.OPTIMIZE)
        self.assertTrue({"s", "u1", "t1"}.issubset(plan.protected_ids))
        self.assertNotIn("r", plan.protected_ids)

    def test_exact_edit_material_bypasses_entire_request(self):
        request = env(
            ContextBlock("u", "user", "apply this edit", turn_index=2),
            ContextBlock("e", "retrieved", 'old_string="exact bytes"\nnew_string="changed"'),
        )
        plan = self.planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.BYPASS)
        self.assertIn("exact_edit_context", plan.reasons)

    def test_historical_decision_does_not_force_bypass_when_active_state_is_preserved(self):
        request = env(
            ContextBlock("d1", "retrieved", "DECISION: use cached result", turn_index=0),
            ContextBlock("d2", "tool_output", "DECISION: validate tenant_id", turn_index=4),
            ContextBlock("u", "user", "what should we do?", turn_index=5),
        )
        plan = self.planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.OPTIMIZE)
        self.assertTrue({"d1", "d2", "u"}.issubset(plan.protected_ids))

    def test_distinct_active_decisions_in_same_turn_bypass(self):
        request = env(
            ContextBlock("d1", "retrieved", "DECISION: use cached result", turn_index=5),
            ContextBlock("d2", "tool_output", "DECISION: validate tenant_id", turn_index=5),
            ContextBlock("u", "user", "what should we do?", turn_index=5),
        )
        plan = self.planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.BYPASS)
        self.assertIn("competing_active_decisions", plan.reasons)

    def test_all_blocks_in_latest_turn_are_protected(self):
        request = env(
            ContextBlock("old", "retrieved", "old context", turn_index=1),
            ContextBlock("obs", "tool_output", "latest evidence", turn_index=3),
            ContextBlock("doc", "retrieved", "current supporting doc", turn_index=3),
            ContextBlock("u", "user", "continue", turn_index=3),
        )
        plan = self.planner.plan(request)
        self.assertTrue({"obs", "doc", "u"}.issubset(plan.protected_ids))
        self.assertNotIn("old", plan.protected_ids)

    def test_unsupported_wire_shape_bypasses(self):
        plan = self.planner.plan(env(ContextBlock("u", "user", "hello"), wire_safe=False))
        self.assertEqual(plan.decision, OptimizationDecision.BYPASS)
        self.assertIn("unsupported_wire_shape", plan.reasons)

    def test_single_decision_anchor_is_protected_without_forcing_bypass(self):
        request = env(
            ContextBlock("d", "retrieved", "DECISION: validate tenant_id"),
            ContextBlock("r", "retrieved", "background detail"),
            ContextBlock("u", "user", "continue", turn_index=2),
        )
        plan = self.planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.OPTIMIZE)
        self.assertIn("d", plan.protected_ids)


class PlannerProtectionTests(unittest.TestCase):
    def test_hard_constraint_and_tool_schema_are_protected(self):
        planner = ContextPlanner()
        request = env(
            ContextBlock("schema", "tool_schema", '{"name":"send_mail"}'),
            ContextBlock("constraint", "retrieved", "NEVER deploy production without approval"),
            ContextBlock("background", "retrieved", "ordinary background"),
            ContextBlock("u", "user", "analyze only", turn_index=5),
        )
        plan = planner.plan(request)
        self.assertIn("schema", plan.protected_ids)
        self.assertIn("constraint", plan.protected_ids)
        self.assertNotIn("background", plan.protected_ids)


if __name__ == "__main__":
    unittest.main()


class StructuredDecisionRiskTests(unittest.TestCase):
    def test_parseable_json_evidence_with_decision_context_bypasses(self):
        planner = ContextPlanner()
        request = env(
            ContextBlock("s", "system", "DECISION: inspect the evidence", turn_index=0),
            ContextBlock("j", "tool_output", '[{"status":"failed"},{"status":"ok"}]', turn_index=1),
            ContextBlock("u", "user", "choose the final decision", turn_index=2),
        )
        plan = planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.BYPASS)
        self.assertIn("structured_decision_context", plan.reasons)

    def test_parseable_json_without_decision_context_remains_eligible(self):
        planner = ContextPlanner()
        request = env(
            ContextBlock("j", "tool_output", '[{"status":"failed"},{"status":"ok"}]', turn_index=1),
            ContextBlock("u", "user", "summarize this data", turn_index=2),
        )
        plan = planner.plan(request)
        self.assertEqual(plan.decision, OptimizationDecision.OPTIMIZE)
