from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    name: str
    passed: bool
    detail: str


class ConformanceFailure(AssertionError):
    pass


def run_conformance(
    cases: Mapping[str, Callable[[], bool]],
) -> tuple[ConformanceResult, ...]:
    results: list[ConformanceResult] = []
    for name in sorted(cases):
        try:
            passed = cases[name]() is True
            detail = "passed" if passed else "returned_false"
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {exc}"
        results.append(ConformanceResult(name=name, passed=passed, detail=detail))
    return tuple(results)


def require_conformance(results: Sequence[ConformanceResult]) -> None:
    failed = sorted(result.name for result in results if not result.passed)
    if failed:
        raise ConformanceFailure(f"conformance failed: {', '.join(failed)}")
