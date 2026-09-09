import tempfile
import unittest
from pathlib import Path

from token_runtime.model import ContextBlock
from token_runtime.reducers import RepeatedLineReducer, ToolOutputReducer
from token_runtime.store import RecoveryStore


class ReducerTests(unittest.TestCase):
    def make_store(self, tmp):
        return RecoveryStore(Path(tmp) / "recovery.db")

    def test_repeated_line_reducer_collapses_run_and_archives_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            repeated = "this is a long repeated diagnostic line with redundant payload"
            block = ContextBlock("r", "retrieved", "\n".join([repeated] * 10 + ["other"]))
            reduction = RepeatedLineReducer().reduce(block, store, protected=False)
            self.assertTrue(reduction.changed)
            self.assertIn("[repeated x10]", reduction.block.text)
            self.assertIsNotNone(reduction.recovery_ref)
            self.assertEqual(store.get(reduction.recovery_ref), block.text.encode())

    def test_protected_block_is_never_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            block = ContextBlock("p", "retrieved", "same\nsame\nsame")
            reduction = RepeatedLineReducer().reduce(block, store, protected=True)
            self.assertFalse(reduction.changed)
            self.assertEqual(reduction.block, block)

    def test_large_old_tool_output_keeps_critical_middle_line_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            head = [f"head {i}" for i in range(12)]
            middle = [f"noise {i}" for i in range(80)]
            middle[40] = "ERROR missing tenant_id; validation failed"
            tail = [f"tail {i}" for i in range(12)]
            text = "\n".join(head + middle + tail)
            block = ContextBlock("old-tool", "tool_output", text, turn_index=1)
            reduction = ToolOutputReducer(min_chars=300).reduce(block, store, protected=False)
            self.assertTrue(reduction.changed)
            self.assertIn("ERROR missing tenant_id; validation failed", reduction.block.text)
            self.assertIn("[TOKEN_REF:", reduction.block.text)
            self.assertEqual(store.get(reduction.recovery_ref), text.encode())

    def test_small_tool_output_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(tmp)
            block = ContextBlock("small", "tool_output", "ok\nall good")
            reduction = ToolOutputReducer(min_chars=300).reduce(block, store, protected=False)
            self.assertFalse(reduction.changed)
            self.assertEqual(reduction.block.text, block.text)


if __name__ == "__main__":
    unittest.main()


class RetrievedSpanReducerTests(unittest.TestCase):
    def test_exact_repeated_word_span_reduces_old_retrieved_block_and_recovers(self):
        from token_runtime.reducers import RetrievedDuplicateReducer
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            phrase = (
                "general background prose about the platform that is plausibly relevant "
                "but not load bearing for this decision."
            )
            original = f"{phrase} {phrase}"
            block = ContextBlock("doc", "retrieved", original)
            reduction = RetrievedDuplicateReducer().reduce(
                block, store, protected=False
            )
            self.assertTrue(reduction.changed)
            self.assertLess(len(reduction.block.text), len(original))
            self.assertIsNotNone(reduction.recovery_ref)
            self.assertEqual(
                store.get(reduction.recovery_ref).decode("utf-8"), original
            )

    def test_non_retrieved_or_protected_block_is_untouched(self):
        from token_runtime.reducers import RetrievedDuplicateReducer
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            text = "alpha beta gamma alpha beta gamma"
            reducer = RetrievedDuplicateReducer()
            self.assertFalse(reducer.reduce(
                ContextBlock("a", "assistant", text), store, protected=False
            ).changed)
            self.assertFalse(reducer.reduce(
                ContextBlock("r", "retrieved", text), store, protected=True
            ).changed)


class WireToolOutputDuplicateReducerTests(unittest.TestCase):
    def test_exact_repeated_span_reduces_old_tool_output_and_recovers(self):
        from token_runtime.reducers import RetrievedDuplicateReducer
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            phrase = "retrieved evidence payload with enough exact words to be safely deduplicated now"
            original = f"{phrase} {phrase}"
            block = ContextBlock("tool-old", "tool_output", original, turn_index=1)
            reduction = RetrievedDuplicateReducer().reduce(block, store, protected=False)
            self.assertTrue(reduction.changed)
            self.assertLess(len(reduction.block.text), len(original))
            self.assertEqual(store.get(reduction.recovery_ref).decode(), original)

    def test_guarded_or_protected_tool_output_is_untouched(self):
        from token_runtime.reducers import RetrievedDuplicateReducer
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStore(Path(tmp) / "recovery.db")
            reducer = RetrievedDuplicateReducer()
            guarded = ContextBlock("g", "tool_output", "DECISION: keep exact state keep exact state")
            self.assertFalse(reducer.reduce(guarded, store, protected=False).changed)
            plain = ContextBlock("p", "tool_output", "alpha beta gamma delta alpha beta gamma delta")
            self.assertFalse(reducer.reduce(plain, store, protected=True).changed)

class JsonToolOutputReducerTests(unittest.TestCase):
    def test_parseable_json_tool_output_is_minified_losslessly_and_recoverable(self):
        import json
        from token_runtime.reducers import JsonToolOutputReducer
        with tempfile.TemporaryDirectory() as tmp:
            store=RecoveryStore(Path(tmp)/'recovery.db')
            original=json.dumps([{'id':i,'status':'failed' if i==4 else 'ok','latency_ms':100+i} for i in range(20)],indent=2)
            block=ContextBlock('json','tool_output',original,turn_index=1)
            reduction=JsonToolOutputReducer().reduce(block,store,protected=False)
            self.assertTrue(reduction.changed)
            self.assertEqual(json.loads(reduction.block.text),json.loads(original))
            self.assertLess(len(reduction.block.text),len(original))
            self.assertEqual(store.get(reduction.recovery_ref).decode(),original)

    def test_generic_tool_reducer_does_not_lossily_compact_parseable_json(self):
        import json
        original=json.dumps([{'id':i,'status':'failed' if i==2 else 'ok'} for i in range(100)],indent=2)
        with tempfile.TemporaryDirectory() as tmp:
            store=RecoveryStore(Path(tmp)/'recovery.db')
            block=ContextBlock('json','tool_output',original,turn_index=1)
            reduction=ToolOutputReducer(min_chars=100).reduce(block,store,protected=False)
            self.assertFalse(reduction.changed)
            self.assertEqual(reduction.block.text,original)

    def test_other_text_reducers_also_skip_parseable_json_tool_output(self):
        import json
        from token_runtime.reducers import RetrievedDuplicateReducer
        original=json.dumps([{'same':'alpha beta gamma delta epsilon zeta eta theta'}]*8,indent=2)
        with tempfile.TemporaryDirectory() as tmp:
            store=RecoveryStore(Path(tmp)/'recovery.db')
            block=ContextBlock('json','tool_output',original,turn_index=1)
            self.assertFalse(RepeatedLineReducer().reduce(block,store,protected=False).changed)
            self.assertFalse(RetrievedDuplicateReducer().reduce(block,store,protected=False).changed)
