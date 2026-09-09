from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable, Protocol

from .model import OptimizationDecision, OptimizationResult, RequestEnvelope
from .planner import ContextPlanner
from .reducers import JsonToolOutputReducer, RepeatedLineReducer, RetrievedDuplicateReducer, ToolOutputReducer
from .store import RecoveryStore


_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(envelope: RequestEnvelope) -> int:
    units = sum(len(_TOKEN_RE.findall(block.text)) for block in envelope.blocks)
    return int(round(units * 1.33))


class ReducerLike(Protocol):
    def reduce(self, block, store: RecoveryStore, *, protected: bool): ...


class OptimizationEngine:
    def __init__(
        self,
        *,
        planner: ContextPlanner,
        store: RecoveryStore,
        reducers: Iterable[ReducerLike] | None = None,
    ):
        self.planner = planner
        self.store = store
        self.reducers = tuple(reducers) if reducers is not None else (
            JsonToolOutputReducer(),
            RepeatedLineReducer(),
            RetrievedDuplicateReducer(),
            ToolOutputReducer(),
        )

    def optimize(self, envelope: RequestEnvelope) -> OptimizationResult:
        before = estimate_tokens(envelope)
        plan = self.planner.plan(envelope)
        if plan.decision is OptimizationDecision.BYPASS:
            return OptimizationResult(
                decision=OptimizationDecision.BYPASS,
                envelope=envelope,
                reasons=plan.reasons,
                before_estimated_tokens=before,
                after_estimated_tokens=before,
            )

        blocks = []
        changed_ids: list[str] = []
        recovery_refs: list[str] = []
        try:
            for original in envelope.blocks:
                current = original
                for reducer in self.reducers:
                    reduction = reducer.reduce(
                        current,
                        self.store,
                        protected=original.id in plan.protected_ids,
                    )
                    current = reduction.block
                    if reduction.changed:
                        if original.id not in changed_ids:
                            changed_ids.append(original.id)
                        if reduction.recovery_ref and reduction.recovery_ref not in recovery_refs:
                            recovery_refs.append(reduction.recovery_ref)
                blocks.append(current)
        except Exception:
            return self._fallback(envelope, before, "fallback_internal_error")

        blocks, dedup_changed, dedup_refs = self._dedup_exact_evidence(
            envelope, blocks, plan.protected_ids
        )
        for block_id in dedup_changed:
            if block_id not in changed_ids:
                changed_ids.append(block_id)
        for ref in dedup_refs:
            if ref not in recovery_refs:
                recovery_refs.append(ref)

        optimized = replace(envelope, blocks=tuple(blocks))
        after = estimate_tokens(optimized)
        if not changed_ids or after >= before:
            return self._fallback(envelope, before, "no_eligible_reduction")
        return OptimizationResult(
            decision=OptimizationDecision.OPTIMIZE,
            envelope=optimized,
            reasons=("optimized",),
            before_estimated_tokens=before,
            after_estimated_tokens=after,
            changed_block_ids=tuple(changed_ids),
            recovery_refs=tuple(recovery_refs),
        )

    def _dedup_exact_evidence(self, envelope, blocks, protected_ids):
        evidence_kinds = {"retrieved", "tool_output"}
        canonical: dict[str, tuple[int, str]] = {}
        for index, (original, current) in enumerate(zip(envelope.blocks, blocks)):
            if original.kind in evidence_kinds:
                canonical[current.text] = (index, original.id)

        out = []
        changed: list[str] = []
        refs: list[str] = []
        for index, (original, current) in enumerate(zip(envelope.blocks, blocks)):
            if original.kind not in evidence_kinds or original.id in protected_ids:
                out.append(current)
                continue
            canonical_index, canonical_id = canonical[current.text]
            if index == canonical_index:
                out.append(current)
                continue
            ref = self.store.put(original.text.encode())
            marker = f"[TOKEN_DUPLICATE_OF:{canonical_id};TOKEN_REF:{ref}]"
            if len(marker) >= len(current.text):
                out.append(current)
                continue
            out.append(replace(current, text=marker))
            changed.append(original.id)
            refs.append(ref)
        return out, tuple(changed), tuple(refs)

    @staticmethod
    def _fallback(envelope: RequestEnvelope, before: int, reason: str) -> OptimizationResult:
        return OptimizationResult(
            decision=OptimizationDecision.BYPASS,
            envelope=envelope,
            reasons=(reason,),
            before_estimated_tokens=before,
            after_estimated_tokens=before,
        )
