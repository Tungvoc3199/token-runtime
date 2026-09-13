import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile

from token_runtime.contracts import ProtocolAdapterContract
from token_runtime.engine import OptimizationEngine
from token_runtime.gemini_adapter import GeminiGenerateContentAdapter
from token_runtime.model import OptimizationDecision
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


def text_payload():
    return {
        "contents": [
            {"role": "user", "parts": [{"text": "current task"}]},
            {"role": "model", "parts": [{"text": "working"}]},
        ],
        "systemInstruction": {"parts": [{"text": "stable policy"}]},
        "cachedContent": "cachedContents/cache-1",
        "generationConfig": {"temperature": 0.2},
        "futureField": {"preserve": True},
    }


class GeminiGenerateContentAdapterTextTests(unittest.TestCase):
    def test_contract_roundtrip_and_text_paths(self):
        adapter = GeminiGenerateContentAdapter()
        self.assertIsInstance(adapter, ProtocolAdapterContract)
        self.assertEqual(adapter.protocol_id, "gemini_generate_content")

        payload = text_payload()
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        self.assertEqual(
            {block.kind for block in envelope.blocks},
            {"system", "user", "assistant"},
        )

        target = next(block for block in envelope.blocks if block.text == "current task")
        changed = replace(
            envelope,
            blocks=tuple(
                replace(block, text="updated task") if block is target else block
                for block in envelope.blocks
            ),
        )
        actual = adapter.serialize(changed)
        expected = deepcopy(payload)
        expected["contents"][0]["parts"][0]["text"] = "updated task"
        self.assertEqual(actual, expected)
        self.assertEqual(actual["cachedContent"], "cachedContents/cache-1")
        self.assertEqual(actual["futureField"], {"preserve": True})

    def test_roleless_text_content_is_treated_as_user_but_non_text_remains_unsafe(self):
        adapter = GeminiGenerateContentAdapter()
        payload = {"contents": [{"parts": [{"text": "hello"}]}]}
        envelope = adapter.parse(payload)
        self.assertTrue(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)
        block = next(block for block in envelope.blocks if block.text == "hello")
        self.assertEqual(block.kind, "user")
        self.assertEqual(block.role, "user")
        self.assertEqual(block.metadata["path"], ("contents", 0, "parts", 0, "text"))

        unsafe_payload = {
            "contents": [{
                "parts": [{"functionResponse": {"name": "lookup", "response": {}}}]
            }]
        }
        unsafe = adapter.parse(unsafe_payload)
        self.assertFalse(unsafe.wire_safe)
        self.assertEqual(adapter.serialize(unsafe), unsafe_payload)


class GeminiGenerateContentAdapterFunctionTests(unittest.TestCase):
    def test_tools_function_call_and_response_are_protected_protocol_material(self):
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": "check status"}]},
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "call_1",
                                "name": "lookup",
                                "args": {"q": "status"},
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "call_1",
                                "name": "lookup",
                                "response": {"status": "green"},
                            }
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "fixture",
                            "parameters": {"type": "OBJECT"},
                        }
                    ]
                }
            ],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "cachedContent": "cachedContents/cache-1",
        }
        adapter = GeminiGenerateContentAdapter()
        envelope = adapter.parse(payload)
        self.assertFalse(envelope.wire_safe)
        self.assertEqual(adapter.serialize(envelope), payload)

        tool_schema = next(block for block in envelope.blocks if block.kind == "tool_schema")
        tool_call = next(block for block in envelope.blocks if block.kind == "tool_call")
        tool_output = next(block for block in envelope.blocks if block.kind == "tool_output")
        self.assertNotIn("path", tool_schema.metadata)
        self.assertNotIn("path", tool_call.metadata)
        self.assertNotIn("path", tool_output.metadata)


    def test_function_response_accepts_both_documented_roles_but_function_text_is_unsafe(self):
        part = {
            "functionResponse": {
                "id": "call_2",
                "name": "lookup",
                "response": {"status": "green"},
            }
        }
        adapter = GeminiGenerateContentAdapter()

        for role in ("user", "function"):
            payload = {"contents": [{"role": role, "parts": [part]}]}
            with self.subTest(role=role):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                output = next(block for block in envelope.blocks if block.kind == "tool_output")
                self.assertNotIn("path", output.metadata)
                self.assertEqual(adapter.serialize(envelope), payload)

        invalid_payload = {
            "contents": [{"role": "function", "parts": [{"text": "not a function response"}]}]
        }
        invalid_envelope = adapter.parse(invalid_payload)
        self.assertFalse(invalid_envelope.wire_safe)
        self.assertEqual(adapter.serialize(invalid_envelope), invalid_payload)

    def test_function_responses_force_engine_passthrough_until_wire_editable(self):
        repeated = {"name": "lookup", "response": {"result": "x" * 100}}
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": "q1"}]},
                {"role": "model", "parts": [{"functionCall": {"name": "lookup", "args": {}}}]},
                {"role": "user", "parts": [{"functionResponse": repeated}]},
                {"role": "model", "parts": [{"functionCall": {"name": "lookup", "args": {}}}]},
                {"role": "user", "parts": [{"functionResponse": repeated}]},
                {"role": "user", "parts": [{"text": "continue"}]},
            ]
        }
        adapter = GeminiGenerateContentAdapter()
        envelope = adapter.parse(payload)
        self.assertFalse(envelope.wire_safe)
        with tempfile.TemporaryDirectory() as tmp:
            result = OptimizationEngine(
                planner=ContextPlanner(),
                store=RecoveryStore(Path(tmp) / "recovery.sqlite"),
            ).optimize(envelope)
        self.assertEqual(result.decision, OptimizationDecision.BYPASS)
        self.assertEqual(result.changed_block_ids, ())
        self.assertEqual(result.before_estimated_tokens, result.after_estimated_tokens)
        self.assertEqual(adapter.serialize(result.envelope), payload)


class GeminiGenerateContentAdapterSafetyTests(unittest.TestCase):
    def test_thought_signature_forces_exact_passthrough(self):
        payloads = (
            {
                "contents": [
                    {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {"name": "lookup", "args": {"q": "x"}},
                                "thoughtSignature": "opaque-signature",
                            }
                        ],
                    }
                ]
            },
            {
                "contents": [
                    {
                        "role": "model",
                        "parts": [
                            {"text": "answer", "thoughtSignature": "opaque-signature"}
                        ],
                    }
                ]
            },
        )
        adapter = GeminiGenerateContentAdapter()
        for payload in payloads:
            with self.subTest(payload=payload):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)
                self.assertTrue(all("path" not in block.metadata for block in envelope.blocks))

    def test_cached_content_must_be_a_valid_resource_reference(self):
        payloads = (
            {"contents": [{"role": "user", "parts": [{"text": "x"}]}], "cachedContent": 3},
            {"contents": [{"role": "user", "parts": [{"text": "x"}]}], "cachedContent": "cache-1"},
        )
        adapter = GeminiGenerateContentAdapter()
        for payload in payloads:
            with self.subTest(payload=payload):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)

    def test_unknown_multimodal_and_code_parts_fail_safe(self):
        parts = (
            {"inlineData": {"mimeType": "image/png", "data": "opaque"}},
            {"fileData": {"mimeType": "image/png", "fileUri": "files/opaque"}},
            {"executableCode": {"language": "PYTHON", "code": "print(1)"}},
            {"futurePart": {"opaque": True}},
        )
        adapter = GeminiGenerateContentAdapter()
        for part in parts:
            payload = {"contents": [{"role": "user", "parts": [{"text": "x"}, part]}]}
            with self.subTest(part=part):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)

    def test_malformed_function_parts_fail_safe(self):
        cases = (
            ("model", {"functionCall": {"args": {}}}),
            ("model", {"functionCall": {"name": "lookup", "args": []}}),
            ("model", {"functionCall": {"name": "lookup", "id": 3}}),
            ("user", {"functionResponse": {"response": {"ok": True}}}),
            ("user", {"functionResponse": {"name": "lookup", "response": []}}),
            ("user", {"functionResponse": {"name": "lookup", "response": {}, "parts": [{"inlineData": {"mimeType": "image/png", "data": "x"}}]}}),
        )
        adapter = GeminiGenerateContentAdapter()
        for role, part in cases:
            payload = {"contents": [{"role": role, "parts": [part]}]}
            with self.subTest(role=role, part=part):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)


class GeminiGenerateContentAdapterToolSurfaceSafetyTests(unittest.TestCase):
    def test_non_function_tools_force_exact_passthrough(self):
        tools = (
            {"googleSearch": {}},
            {"codeExecution": {}},
            {"urlContext": {}},
            {"mcpServers": [{"name": "opaque"}]},
        )
        adapter = GeminiGenerateContentAdapter()
        for tool in tools:
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "x"}]}],
                "tools": [tool],
            }
            with self.subTest(tool=tool):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)

    def test_malformed_function_declarations_force_exact_passthrough(self):
        tools = (
            {"functionDeclarations": []},
            {"functionDeclarations": [{}]},
            {"functionDeclarations": [{"name": 3}]},
            {"functionDeclarations": "not-a-list"},
        )
        adapter = GeminiGenerateContentAdapter()
        for tool in tools:
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "x"}]}],
                "tools": [tool],
            }
            with self.subTest(tool=tool):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)

    def test_unknown_function_part_siblings_force_exact_passthrough(self):
        parts = (
            {"functionCall": {"name": "lookup", "args": {}}, "futureMetadata": "opaque"},
            {
                "functionResponse": {"name": "lookup", "response": {}},
                "futureMetadata": "opaque",
            },
        )
        adapter = GeminiGenerateContentAdapter()
        for part in parts:
            role = "model" if "functionCall" in part else "user"
            payload = {"contents": [{"role": role, "parts": [part]}]}
            with self.subTest(part=part):
                envelope = adapter.parse(payload)
                self.assertFalse(envelope.wire_safe)
                self.assertEqual(adapter.serialize(envelope), payload)


if __name__ == "__main__":
    unittest.main()
