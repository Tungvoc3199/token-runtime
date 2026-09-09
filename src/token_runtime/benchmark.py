from __future__ import annotations

from dataclasses import dataclass

from .model import OptimizationDecision, RequestEnvelope


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    name: str
    envelope: RequestEnvelope


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    name: str
    decision: str
    before_estimated_tokens: int
    after_estimated_tokens: int
    saved_pct: float
    reasons: tuple[str, ...]
    protected_byte_fidelity: float
    recoverable: bool


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    cases: tuple[BenchmarkCaseResult, ...]
    baseline_estimated_tokens: int
    optimized_estimated_tokens: int
    total_saved_pct: float
    optimized_count: int
    bypass_count: int
    eligible_saved_pct: float


def _fidelity(original: RequestEnvelope, optimized: RequestEnvelope, protected_ids) -> float:
    original_by_id = {block.id: block.text for block in original.blocks}
    optimized_by_id = {block.id: block.text for block in optimized.blocks}
    ids = tuple(protected_ids)
    if not ids:
        return 1.0
    intact = sum(
        1 for block_id in ids
        if optimized_by_id.get(block_id) == original_by_id.get(block_id)
    )
    return round(intact / len(ids), 6)


def _recoverable(engine, refs: tuple[str, ...]) -> bool:
    try:
        for ref in refs:
            engine.store.get(ref)
    except Exception:
        return False
    return True


def benchmark_cases(cases, engine) -> BenchmarkReport:
    rows: list[BenchmarkCaseResult] = []
    baseline_total = optimized_total = 0
    eligible_before = eligible_after = 0
    optimized_count = 0

    for case in cases:
        plan = engine.planner.plan(case.envelope)
        result = engine.optimize(case.envelope)
        before = result.before_estimated_tokens
        after = result.after_estimated_tokens
        baseline_total += before
        optimized_total += after
        saved_pct = round((before - after) * 100 / before, 2) if before else 0.0
        if result.decision is OptimizationDecision.OPTIMIZE:
            optimized_count += 1
            eligible_before += before
            eligible_after += after
        rows.append(BenchmarkCaseResult(
            name=case.name,
            decision=result.decision.value,
            before_estimated_tokens=before,
            after_estimated_tokens=after,
            saved_pct=saved_pct,
            reasons=result.reasons,
            protected_byte_fidelity=_fidelity(
                case.envelope, result.envelope, plan.protected_ids
            ),
            recoverable=_recoverable(engine, result.recovery_refs),
        ))

    total_saved_pct = (
        round((baseline_total - optimized_total) * 100 / baseline_total, 2)
        if baseline_total else 0.0
    )
    eligible_saved_pct = (
        round((eligible_before - eligible_after) * 100 / eligible_before, 2)
        if eligible_before else 0.0
    )
    return BenchmarkReport(
        cases=tuple(rows),
        baseline_estimated_tokens=baseline_total,
        optimized_estimated_tokens=optimized_total,
        total_saved_pct=total_saved_pct,
        optimized_count=optimized_count,
        bypass_count=len(rows) - optimized_count,
        eligible_saved_pct=eligible_saved_pct,
    )
