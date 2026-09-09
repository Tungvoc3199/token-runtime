from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, MutableMapping, Sequence

from .model import ContextBlock, RequestEnvelope


def _set_path(root: Any, path: Sequence[Any], value: str) -> None:
    target = root
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _kind_for_role(role: str) -> str:
    if role in {"system", "developer", "user"}:
        return role
    if role == "tool":
        return "tool_output"
    return "assistant"


def _block(block_id: str, kind: str, text: str, *, role=None, turn=0, path=None) -> ContextBlock:
    metadata = {} if path is None else {"path": tuple(path)}
    return ContextBlock(block_id, kind, text, role=role, turn_index=turn, metadata=metadata)


class _AdapterBase:
    name = "base"

    def serialize(self, envelope: RequestEnvelope) -> dict[str, Any]:
        payload = deepcopy(envelope.opaque["original_payload"])
        for block in envelope.blocks:
            path = block.metadata.get("path")
            if path:
                _set_path(payload, path, block.text)
        return payload

    @staticmethod
    def _tool_blocks(tools: Any) -> list[ContextBlock]:
        if not isinstance(tools, list):
            return []
        return [
            _block(f"tool-schema-{i}", "tool_schema", json.dumps(tool, sort_keys=True, separators=(",", ":")))
            for i, tool in enumerate(tools)
        ]


class ResponsesAdapter(_AdapterBase):
    name = "responses"

    def parse(self, payload: Mapping[str, Any]) -> RequestEnvelope:
        original = deepcopy(dict(payload))
        blocks: list[ContextBlock] = []
        safe = True
        instructions = payload.get("instructions")
        if isinstance(instructions, str):
            blocks.append(_block("instructions", "system", instructions, role="system", path=("instructions",)))
        elif instructions is not None:
            safe = False

        blocks.extend(self._tool_blocks(payload.get("tools")))
        input_value = payload.get("input")
        if isinstance(input_value, str):
            blocks.append(_block("input", "user", input_value, role="user", path=("input",)))
        elif isinstance(input_value, list):
            for i, item in enumerate(input_value):
                item_blocks, item_safe = self._parse_input_item(i, item)
                blocks.extend(item_blocks)
                safe = safe and item_safe
        elif input_value is not None:
            safe = False

        return RequestEnvelope(
            blocks=tuple(blocks),
            opaque={"original_payload": original},
            adapter=self.name,
            wire_safe=safe,
        )

    def _parse_input_item(self, index: int, item: Any) -> tuple[list[ContextBlock], bool]:
        if not isinstance(item, Mapping):
            return [], False
        item_type = item.get("type")
        if item_type == "function_call_output":
            output = item.get("output")
            if not isinstance(output, str):
                return [], False
            return [_block(f"input-{index}", "tool_output", output, role="tool", turn=index, path=("input", index, "output"))], True
        if item_type == "function_call":
            return [_block(f"input-{index}", "tool_call", json.dumps(dict(item), sort_keys=True))], True

        role = item.get("role")
        if not isinstance(role, str):
            return [], False
        content = item.get("content")
        kind = _kind_for_role(role)
        if isinstance(content, str):
            return [
                _block(f"input-{index}", kind, content, role=role, turn=index, path=("input", index, "content"))
            ], True
        if isinstance(content, list):
            blocks: list[ContextBlock] = []
            safe = True
            for j, part in enumerate(content):
                if not isinstance(part, Mapping):
                    safe = False
                    continue
                part_type = part.get("type")
                text = part.get("text")
                if part_type not in {"input_text", "output_text", "text"} or not isinstance(text, str):
                    safe = False
                    continue
                blocks.append(
                    _block(
                        f"input-{index}-content-{j}",
                        kind,
                        text,
                        role=role,
                        turn=index,
                        path=("input", index, "content", j, "text"),
                    )
                )
            return blocks, safe
        return [], content is None


class ChatCompletionsAdapter(_AdapterBase):
    name = "chat_completions"

    def parse(self, payload: Mapping[str, Any]) -> RequestEnvelope:
        original = deepcopy(dict(payload))
        blocks: list[ContextBlock] = self._tool_blocks(payload.get("tools"))
        safe = True
        messages = payload.get("messages")
        if not isinstance(messages, list):
            safe = False
            messages = []

        for i, message in enumerate(messages):
            if not isinstance(message, Mapping):
                safe = False
                continue
            role = message.get("role")
            if not isinstance(role, str):
                safe = False
                continue
            kind = _kind_for_role(role)
            content = message.get("content")
            if isinstance(content, str):
                blocks.append(
                    _block(f"message-{i}", kind, content, role=role, turn=i, path=("messages", i, "content"))
                )
            elif isinstance(content, list):
                for j, part in enumerate(content):
                    if not isinstance(part, Mapping) or part.get("type") != "text" or not isinstance(part.get("text"), str):
                        safe = False
                        continue
                    blocks.append(
                        _block(
                            f"message-{i}-content-{j}", kind, part["text"], role=role, turn=i,
                            path=("messages", i, "content", j, "text"),
                        )
                    )
            elif content is not None:
                safe = False
            tool_calls = message.get("tool_calls")
            if tool_calls is not None:
                if not isinstance(tool_calls, list):
                    safe = False
                else:
                    blocks.append(_block(f"message-{i}-tool-calls", "tool_call", json.dumps(tool_calls, sort_keys=True), role=role, turn=i))

        return RequestEnvelope(
            blocks=tuple(blocks),
            opaque={"original_payload": original},
            adapter=self.name,
            wire_safe=safe,
        )
