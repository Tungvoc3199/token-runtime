import unittest

from token_runtime.model import (
    ContextBlock,
    OptimizationDecision,
    OptimizationResult,
    RequestEnvelope,
)


class ModelTests(unittest.TestCase):
    def test_request_envelope_preserves_block_order_and_opaque_fields(self):
        blocks = (
            ContextBlock("sys", "system", "SYSTEM bytes", role="system"),
            ContextBlock("tool", "tool_output", "TOOL bytes", turn_index=1),
            ContextBlock("user", "user", "USER bytes", role="user", turn_index=2),
        )
        opaque = {"model": "vscode-debug", "temperature": 0.2}
        envelope = RequestEnvelope(blocks=blocks, opaque=opaque, adapter="responses")

        self.assertEqual([b.id for b in envelope.blocks], ["sys", "tool", "user"])
        self.assertEqual([b.text for b in envelope.blocks], ["SYSTEM bytes", "TOOL bytes", "USER bytes"])
        self.assertEqual(envelope.opaque, opaque)
        self.assertEqual(envelope.adapter, "responses")

    def test_optimization_result_tracks_original_and_optimized_counts(self):
        envelope = RequestEnvelope(blocks=(ContextBlock("u", "user", "hello"),))
        result = OptimizationResult(
            decision=OptimizationDecision.BYPASS,
            envelope=envelope,
            reasons=("no_eligible_reduction",),
            before_estimated_tokens=5,
            after_estimated_tokens=5,
        )
        self.assertIs(result.envelope, envelope)
        self.assertEqual(result.decision, OptimizationDecision.BYPASS)
        self.assertEqual(result.reasons, ("no_eligible_reduction",))
        self.assertEqual(result.changed_block_ids, ())
        self.assertEqual(result.recovery_refs, ())


if __name__ == "__main__":
    unittest.main()
