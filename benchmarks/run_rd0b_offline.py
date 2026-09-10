from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from token_runtime.benchmark import BenchmarkCase, benchmark_cases
from token_runtime.engine import OptimizationEngine
from token_runtime.model import ContextBlock, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore


def load_corpus(corpus: Path) -> list[BenchmarkCase]:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    cases: list[BenchmarkCase] = []
    for item in manifest["trajectories"]:
        data = json.loads((corpus / item["file"]).read_text(encoding="utf-8"))
        blocks: list[ContextBlock] = []
        for turn in data["turns"]:
            for index, block in enumerate(turn["blocks"]):
                blocks.append(ContextBlock(
                    id=f"t{turn['index']}-{index}-{block['id']}",
                    kind=block["kind"],
                    text=block["text"],
                    role=block.get("role"),
                    turn_index=turn["index"],
                ))
        cases.append(
            BenchmarkCase(item.get("title", item["file"]), RequestEnvelope(tuple(blocks)))
        )
    return cases


def build_payload(cases: list[BenchmarkCase]) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        engine = OptimizationEngine(
            planner=ContextPlanner(),
            store=RecoveryStore(Path(tmp) / "recovery.db"),
        )
        report = benchmark_cases(cases, engine)

    payload: dict[str, object] = {
        "corpus_cases": len(report.cases),
        "baseline_estimated_tokens": report.baseline_estimated_tokens,
        "optimized_estimated_tokens": report.optimized_estimated_tokens,
        "total_saved_pct": report.total_saved_pct,
        "eligible_saved_pct": report.eligible_saved_pct,
        "optimized_count": report.optimized_count,
        "bypass_count": report.bypass_count,
        "all_protected_fidelity": all(
            case.protected_byte_fidelity == 1.0 for case in report.cases
        ),
        "all_recoverable": all(case.recoverable for case in report.cases),
        "reason_counts": {},
    }
    reason_counts = payload["reason_counts"]
    assert isinstance(reason_counts, dict)
    for case in report.cases:
        for reason in case.reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    payload = build_payload(load_corpus(args.corpus))
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
