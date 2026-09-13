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


class GeminiGenerateContentAdapter:
    protocol_id = "gemini_generate_content"

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

        if "cachedContent" in payload:
            cached_content = payload.get("cachedContent")
            safe = (
                isinstance(cached_content, str)
                and cached_content.startswith("cachedContents/")
                and len(cached_content) > len("cachedContents/")
            )

        system_blocks, system_safe = self._parse_system(payload.get("systemInstruction"))
        blocks.extend(system_blocks)
        safe = safe and system_safe

        tool_blocks, tools_safe = self._parse_tools(payload.get("tools"))
        blocks.extend(tool_blocks)
        safe = safe and tools_safe

        contents = payload.get("contents")
        if not isinstance(contents, list) or not contents:
            safe = False
            contents = []

        for index, content in enumerate(contents):
            content_blocks, content_safe = self._parse_content(index, content)
            blocks.extend(content_blocks)
            safe = safe and content_safe

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
        if not isinstance(system, Mapping):
            return [], False
        parts = system.get("parts")
        if not isinstance(parts, list) or not parts:
            return [], False

        blocks: list[ContextBlock] = []
        safe = True
        for index, part in enumerate(parts):
            if not isinstance(part, Mapping) or not isinstance(part.get("text"), str):
                safe = False
                continue
            if set(part) != {"text"}:
                safe = False
                continue
            blocks.append(
                _block(
                    f"system-{index}",
                    "system",
                    part["text"],
                    role="system",
                    path=("systemInstruction", "parts", index, "text"),
                )
            )
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
            declarations = tool.get("functionDeclarations")
            valid = (
                set(tool) == {"functionDeclarations"}
                and isinstance(declarations, list)
                and bool(declarations)
                and all(
                    isinstance(declaration, Mapping)
                    and isinstance(declaration.get("name"), str)
                    for declaration in declarations
                )
            )
            blocks.append(_block(f"tool-schema-{index}", "tool_schema", _encoded(tool)))
            safe = safe and valid
        return blocks, safe

    def _parse_content(
        self,
        index: int,
        content: Any,
    ) -> tuple[list[ContextBlock], bool]:
        if not isinstance(content, Mapping):
            return [], False
        role = content.get("role")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            return [], False
        if role is None:
            roleless_text = all(
                isinstance(part, Mapping)
                and set(part) == {"text"}
                and isinstance(part.get("text"), str)
                for part in parts
            )
            if not roleless_text:
                return [], False
            role = "user"
        if role not in {"user", "model", "function"}:
            return [], False

        blocks: list[ContextBlock] = []
        safe = True
        for part_index, part in enumerate(parts):
            part_blocks, part_safe = self._parse_part(index, part_index, role, part)
            blocks.extend(part_blocks)
            safe = safe and part_safe
        return blocks, safe

    @staticmethod
    def _parse_part(
        content_index: int,
        part_index: int,
        role: str,
        part: Any,
    ) -> tuple[list[ContextBlock], bool]:
        if not isinstance(part, Mapping):
            return [], False

        if "thoughtSignature" in part or "thought" in part:
            return [
                _block(
                    f"content-{content_index}-protocol-{part_index}",
                    "protocol_state",
                    _encoded(part),
                    role="assistant" if role == "model" else role,
                    turn=content_index,
                )
            ], False

        if "text" in part:
            text = part.get("text")
            if role not in {"user", "model"} or not isinstance(text, str):
                return [], False
            if set(part) != {"text"}:
                return [], False
            kind = "assistant" if role == "model" else "user"
            return [
                _block(
                    f"content-{content_index}-part-{part_index}",
                    kind,
                    text,
                    role=kind,
                    turn=content_index,
                    path=("contents", content_index, "parts", part_index, "text"),
                )
            ], True

        if "functionCall" in part:
            call = part.get("functionCall")
            valid = (
                set(part) == {"functionCall"}
                and role == "model"
                and isinstance(call, Mapping)
                and isinstance(call.get("name"), str)
                and ("id" not in call or isinstance(call.get("id"), str))
                and ("args" not in call or isinstance(call.get("args"), Mapping))
            )
            return [
                _block(
                    f"content-{content_index}-function-call-{part_index}",
                    "tool_call",
                    _encoded(part),
                    role="assistant",
                    turn=content_index,
                )
            ], valid

        if "functionResponse" in part:
            response = part.get("functionResponse")
            valid = (
                set(part) == {"functionResponse"}
                and role in {"user", "function"}
                and isinstance(response, Mapping)
                and isinstance(response.get("name"), str)
                and isinstance(response.get("response"), Mapping)
                and ("id" not in response or isinstance(response.get("id"), str))
                and not response.get("parts")
            )
            kind = "tool_output" if valid else "protocol_state"
            return [
                _block(
                    f"content-{content_index}-function-response-{part_index}",
                    kind,
                    _encoded(part),
                    role="tool",
                    turn=content_index,
                )
            ], False

        return [], False
