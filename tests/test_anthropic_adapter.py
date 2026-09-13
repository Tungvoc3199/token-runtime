import unittest
from copy import deepcopy
from dataclasses import replace

from token_runtime.anthropic_adapter import AnthropicMessagesAdapter
from token_runtime.contracts import ProtocolAdapterContract
from token_runtime.model import OptimizationDecision
from token_runtime.planner import ContextPlanner


def supported_payload():
    return {
        "model": "opaque-model",
        "max_tokens": 1024,
        "system": [
            {
                "type": "text",
                "text": "stable policy",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "current task",
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "checking"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "lookup",
                        "input": {"q": "status"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [
                            {
                                "type": "text",
                                "text": "status=green",
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            },
        ],
        "tools": [
            {
                "name": "lookup",
                "description": "fixture",
                "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "thinking": {"type": "adaptive"},
        "stream": True,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
        "future_field": {"preserve": True},
    }


class AnthropicMessagesAdapterTests(unittest.TestCase):
    def test_adapter_satisfies_protocol_contract_and_supported_fixture_round_trips(self):
        adapter = AnthropicMessagesAdapter()
        self.assertIsInstance(adapter, ProtocolAdapterContract)
        self.assertEqual(adapter.protocol_id, "anthropic_messages")

        payload = supported_payload()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        kinds = {block.kind for block in envelope.blocks}
        self.assertTrue(
            {"system", "user", "assistant", "tool_schema", "tool_call", "tool_output"}
            <= kinds
        )

    def test_text_mutation_changes_only_declared_path_and_preserves_cache_metadata(self):
        adapter = AnthropicMessagesAdapter()
        payload = supported_payload()
        envelope = adapter.parse(payload)
        target = next(
            block
            for block in envelope.blocks
            if block.text == "current task" and block.metadata.get("path")
        )
        changed = replace(
            envelope,
            blocks=tuple(
                replace(block, text="updated task") if block is target else block
                for block in envelope.blocks
            ),
        )
        actual = adapter.serialize(changed)
        expected = deepcopy(payload)
        expected["messages"][0]["content"][0]["text"] = "updated task"
        self.assertEqual(actual, expected)
        self.assertEqual(
            actual["messages"][0]["content"][0]["cache_control"],
            {"type": "ephemeral", "ttl": "1h"},
        )
        self.assertEqual(actual["tools"], payload["tools"])
        self.assertEqual(actual["future_field"], payload["future_field"])

    def test_tool_use_is_protected_and_textual_tool_result_is_editable_tool_output(self):
        adapter = AnthropicMessagesAdapter()
        envelope = adapter.parse(supported_payload())
        tool_call = next(block for block in envelope.blocks if block.kind == "tool_call")
        tool_output = next(
            block for block in envelope.blocks if block.text == "status=green"
        )
        self.assertNotIn("path", tool_call.metadata)
        self.assertEqual(tool_output.kind, "tool_output")
        self.assertEqual(
            tool_output.metadata["path"],
            ("messages", 2, "content", 0, "content", 0, "text"),
        )

    def test_replayed_thinking_blocks_force_exact_passthrough(self):
        payload = {
            "model": "opaque-model",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "opaque", "signature": "sig"},
                        {"type": "redacted_thinking", "data": "ciphertext"},
                        {
                            "type": "tool_use",
                            "id": "toolu_2",
                            "name": "lookup",
                            "input": {"q": "x"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_2",
                            "content": "done",
                        }
                    ],
                },
            ],
        }
        adapter = AnthropicMessagesAdapter()
        envelope = adapter.parse(payload)
        self.assertFalse(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        protocol_state = [
            block for block in envelope.blocks if block.kind == "protocol_state"
        ]
        self.assertEqual(len(protocol_state), 2)
        self.assertTrue(all("path" not in block.metadata for block in protocol_state))

    def test_multimodal_unknown_and_unsupported_role_shapes_fail_safe(self):
        payloads = (
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "opaque",
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "future_block", "value": "opaque"}],
                    }
                ],
            },
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [{"role": "system", "content": "not allowed here"}],
            },
        )
        adapter = AnthropicMessagesAdapter()
        for payload in payloads:
            with self.subTest(payload=payload):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)


class AnthropicCitationSafetyTests(unittest.TestCase):
    def test_cited_text_blocks_force_exact_passthrough(self):
        payloads = (
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "system": [{
                    "type": "text",
                    "text": "cited system",
                    "citations": [{"type": "char_location", "cited_text": "cited"}],
                }],
                "messages": [{"role": "user", "content": "continue"}],
            },
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": [{
                    "type": "text",
                    "text": "cited message",
                    "citations": [{"type": "char_location", "cited_text": "cited"}],
                }]}],
            },
            {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": "toolu_3",
                    "content": [{
                        "type": "text",
                        "text": "cited tool result",
                        "citations": [{"type": "char_location", "cited_text": "cited"}],
                    }],
                }]}],
            },
        )
        adapter = AnthropicMessagesAdapter()
        for payload in payloads:
            with self.subTest(payload=payload):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)


class AnthropicMalformedToolSafetyTests(unittest.TestCase):
    def test_malformed_tool_use_forces_exact_passthrough(self):
        malformed = (
            {"type": "tool_use", "name": "lookup", "input": {}},
            {"type": "tool_use", "id": 3, "name": "lookup", "input": {}},
            {"type": "tool_use", "id": "toolu_4", "input": {}},
            {"type": "tool_use", "id": "toolu_4", "name": 3, "input": {}},
            {"type": "tool_use", "id": "toolu_4", "name": "lookup"},
            {"type": "tool_use", "id": "toolu_4", "name": "lookup", "input": []},
        )
        adapter = AnthropicMessagesAdapter()
        for part in malformed:
            payload = {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [{"role": "assistant", "content": [part]}],
            }
            with self.subTest(part=part):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)

    def test_malformed_tool_result_reference_forces_exact_passthrough(self):
        malformed = (
            {"type": "tool_result", "content": "done"},
            {"type": "tool_result", "tool_use_id": 3, "content": "done"},
            {"type": "tool_result", "content": [{"type": "text", "text": "done"}]},
        )
        adapter = AnthropicMessagesAdapter()
        for part in malformed:
            payload = {
                "model": "opaque-model",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": [part]}],
            }
            with self.subTest(part=part):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertTrue(all("path" not in block.metadata for block in envelope.blocks))
                self.assertEqual(adapter.serialize(envelope), payload)

class AnthropicFablePreservedThinkingRegressionTests(unittest.TestCase):
    def test_fable_51_replayed_thinking_remains_hard_bypass(self):
        payload = {
            "model": "claude-fable-5-1",
            "max_tokens": 128,
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "opaque", "signature": "sig"},
                    {"type": "text", "text": "prior"},
                ]},
                {"role": "user", "content": "continue"},
            ],
        }
        adapter = AnthropicMessagesAdapter()
        envelope = adapter.parse(payload)
        plan = ContextPlanner().plan(envelope)
        self.assertFalse(envelope.wire_safe)
        self.assertEqual(plan.decision, OptimizationDecision.BYPASS)
        self.assertIn("unsupported_wire_shape", plan.reasons)
        self.assertEqual(adapter.serialize(envelope), payload)


if __name__ == "__main__":
    unittest.main()
