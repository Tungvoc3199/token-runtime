import unittest

from token_runtime.adapters import ChatCompletionsAdapter, ResponsesAdapter


class ResponsesAdapterTests(unittest.TestCase):
    def test_text_payload_round_trips_unknown_fields(self):
        payload = {
            "model": "vscode-debug",
            "instructions": "Keep exact constraints.",
            "input": [
                {"role": "assistant", "content": "old context"},
                {"role": "user", "content": [{"type": "input_text", "text": "current task"}]},
                {"type": "function_call_output", "call_id": "c1", "output": "tool result"},
            ],
            "tools": [{"type": "function", "name": "query", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "medium"},
            "metadata": {"trace": "keep-me"},
        }
        adapter = ResponsesAdapter()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        self.assertIn("system", [block.kind for block in envelope.blocks])
        self.assertIn("tool_output", [block.kind for block in envelope.blocks])
        self.assertIn("tool_schema", [block.kind for block in envelope.blocks])

    def test_multimodal_payload_is_marked_unsafe_and_round_trips(self):
        payload = {
            "model": "x",
            "input": [{"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}],
        }
        adapter = ResponsesAdapter()
        envelope = adapter.parse(payload)
        self.assertFalse(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)


class ChatAdapterTests(unittest.TestCase):
    def test_chat_payload_round_trips_and_classifies_tool_message(self):
        payload = {
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
        adapter = ChatCompletionsAdapter()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        tool = next(block for block in envelope.blocks if block.kind == "tool_output")
        self.assertEqual(tool.text, "ERROR timeout")

    def test_changed_text_block_serializes_only_its_text_path(self):
        payload = {
            "model": "gpt-test",
            "messages": [
                {"role": "assistant", "content": "old\nold\nold"},
                {"role": "user", "content": "current"},
            ],
            "seed": 7,
        }
        adapter = ChatCompletionsAdapter()
        envelope = adapter.parse(payload)
        first = envelope.blocks[0]
        from dataclasses import replace
        changed = replace(
            envelope,
            blocks=(replace(first, text="new context"), envelope.blocks[1]),
        )
        serialized = adapter.serialize(changed)
        self.assertEqual(serialized["messages"][0]["content"], "new context")
        self.assertEqual(serialized["messages"][1]["content"], "current")
        self.assertEqual(serialized["seed"], 7)


if __name__ == "__main__":
    unittest.main()
