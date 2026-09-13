from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from .model import ContextBlock, RequestEnvelope


def _set_path(root: Any, path: Sequence[Any], value: str) -> None:
    target = root
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _block(
    block_id: str,
    kind: str,
    text: str,
    *,
    role: str | None = None,
    turn: int = 0,
    path: Sequence[Any] | None = None,
) -> ContextBlock:
    metadata = {} if path is None else {"path": tuple(path)}
    return ContextBlock(
        block_id,
        kind,
        text,
        role=role,
        turn_index=turn,
        metadata=metadata,
    )


def _encoded(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


class AnthropicMessagesAdapter:
    protocol_id = "anthropic_messages"

    def serialize(self, envelope: RequestEnvelope) -> dict[str, Any]:
        payload = deepcopy(envelope.opaque["original_payload"])
        for block in envelope.blocks:
            path = block.metadata.get("path")
            if path:
                _set_path(payload, path, block.text)
        return payload

    def parse(self, payload: Mapping[str, Any]) -> RequestEnvelope:
        original = deepcopy(dict(payload))
        blocks: list[ContextBlock] = []
        safe = True

        system_blocks, system_safe = self._parse_system(payload.get("system"))
        blocks.extend(system_blocks)
        safe = safe and system_safe

        tool_blocks, tools_safe = self._parse_tools(payload.get("tools"))
        blocks.extend(tool_blocks)
        safe = safe and tools_safe

        messages = payload.get("messages")
        if not isinstance(messages, list):
            safe = False
            messages = []

        for index, message in enumerate(messages):
            message_blocks, message_safe = self._parse_message(index, message)
            blocks.extend(message_blocks)
            safe = safe and message_safe

        return RequestEnvelope(
            blocks=tuple(blocks),
            opaque={"original_payload": original},
            adapter=self.protocol_id,
            wire_safe=safe,
        )

    @staticmethod
    def _parse_system(system: Any) -> tuple[list[ContextBlock], bool]:
        if system is None:
            return [], True
        if isinstance(system, str):
            return [
                _block("system", "system", system, role="system", path=("system",))
            ], True
        if not isinstance(system, list):
            return [], False

        blocks: list[ContextBlock] = []
        safe = True
        for index, part in enumerate(system):
            if (
                not isinstance(part, Mapping)
                or part.get("type") != "text"
                or not isinstance(part.get("text"), str)
            ):
                safe = False
                continue
            cited = part.get("citations") is not None
            blocks.append(
                _block(
                    f"system-{index}",
                    "system",
                    part["text"],
                    role="system",
                    path=None if cited else ("system", index, "text"),
                )
            )
            safe = safe and not cited
        return blocks, safe

    @staticmethod
    def _parse_tools(tools: Any) -> tuple[list[ContextBlock], bool]:
        if tools is None:
            return [], True
        if not isinstance(tools, list):
            return [], False
        blocks: list[ContextBlock] = []
        safe = True
        for index, tool in enumerate(tools):
            if not isinstance(tool, Mapping):
                safe = False
                continue
            blocks.append(
                _block(
                    f"tool-schema-{index}",
                    "tool_schema",
                    _encoded(tool),
                )
            )
        return blocks, safe

    def _parse_message(
        self,
        index: int,
        message: Any,
    ) -> tuple[list[ContextBlock], bool]:
        if not isinstance(message, Mapping):
            return [], False
        role = message.get("role")
        if role not in {"user", "assistant"}:
            return [], False

        content = message.get("content")
        if isinstance(content, str):
            return [
                _block(
                    f"message-{index}",
                    role,
                    content,
                    role=role,
                    turn=index,
                    path=("messages", index, "content"),
                )
            ], True

        if not isinstance(content, list):
            return [], False

        blocks: list[ContextBlock] = []
        safe = True
        for part_index, part in enumerate(content):
            part_blocks, part_safe = self._parse_content_block(
                message_index=index,
                part_index=part_index,
                role=role,
                part=part,
            )
            blocks.extend(part_blocks)
            safe = safe and part_safe
        return blocks, safe

    def _parse_content_block(
        self,
        *,
        message_index: int,
        part_index: int,
        role: str,
        part: Any,
    ) -> tuple[list[ContextBlock], bool]:
        if not isinstance(part, Mapping):
            return [], False

        part_type = part.get("type")
        if part_type == "text":
            text = part.get("text")
            if not isinstance(text, str):
                return [], False
            cited = part.get("citations") is not None
            return [
                _block(
                    f"message-{message_index}-content-{part_index}",
                    role,
                    text,
                    role=role,
                    turn=message_index,
                    path=(
                        None
                        if cited
                        else ("messages", message_index, "content", part_index, "text")
                    ),
                )
            ], not cited

        if part_type == "tool_use":
            valid_tool_use = (
                role == "assistant"
                and isinstance(part.get("id"), str)
                and isinstance(part.get("name"), str)
                and isinstance(part.get("input"), Mapping)
            )
            return [
                _block(
                    f"message-{message_index}-tool-use-{part_index}",
                    "tool_call",
                    _encoded(part),
                    role=role,
                    turn=message_index,
                )
            ], valid_tool_use

        if part_type == "tool_result":
            return self._parse_tool_result(
                message_index=message_index,
                part_index=part_index,
                role=role,
                part=part,
            )

        if part_type in {"thinking", "redacted_thinking"}:
            return [
                _block(
                    f"message-{message_index}-protocol-{part_index}",
                    "protocol_state",
                    _encoded(part),
                    role=role,
                    turn=message_index,
                )
            ], False

        return [], False

    @staticmethod
    def _parse_tool_result(
        *,
        message_index: int,
        part_index: int,
        role: str,
        part: Mapping[str, Any],
    ) -> tuple[list[ContextBlock], bool]:
        content = part.get("content")
        base_path = ("messages", message_index, "content", part_index, "content")
        valid_reference = role == "user" and isinstance(part.get("tool_use_id"), str)
        if isinstance(content, str):
            return [
                _block(
                    f"message-{message_index}-tool-result-{part_index}",
                    "tool_output",
                    content,
                    role="tool",
                    turn=message_index,
                    path=base_path if valid_reference else None,
                )
            ], valid_reference
        if not isinstance(content, list):
            return [], False

        blocks: list[ContextBlock] = []
        safe = valid_reference
        for nested_index, nested in enumerate(content):
            if (
                not isinstance(nested, Mapping)
                or nested.get("type") != "text"
                or not isinstance(nested.get("text"), str)
            ):
                safe = False
                continue
            cited = nested.get("citations") is not None
            blocks.append(
                _block(
                    (
                        f"message-{message_index}-tool-result-"
                        f"{part_index}-content-{nested_index}"
                    ),
                    "tool_output",
                    nested["text"],
                    role="tool",
                    turn=message_index,
                    path=(
                        None
                        if cited or not valid_reference
                        else base_path + (nested_index, "text")
                    ),
                )
            )
            safe = safe and not cited
        return blocks, safe
