from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class OptimizationDecision(str, Enum):
    BYPASS = "bypass"
    OPTIMIZE = "optimize"


@dataclass(frozen=True, slots=True)
class ContextBlock:
    id: str
    kind: str
    text: str
    role: str | None = None
    turn_index: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    blocks: tuple[ContextBlock, ...]
    opaque: Mapping[str, Any] = field(default_factory=dict)
    adapter: str = "normalized"
    wire_safe: bool = True


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    decision: OptimizationDecision
    envelope: RequestEnvelope
    reasons: tuple[str, ...]
    before_estimated_tokens: int
    after_estimated_tokens: int
    changed_block_ids: tuple[str, ...] = ()
    recovery_refs: tuple[str, ...] = ()
