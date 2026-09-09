import argparse
import json
import tempfile
from pathlib import Path

from token_runtime.benchmark import BenchmarkCase, benchmark_cases
from token_runtime.engine import OptimizationEngine
from token_runtime.model import ContextBlock, RequestEnvelope
from token_runtime.planner import ContextPlanner
from token_runtime.store import RecoveryStore

parser = argparse.ArgumentParser(description="Run TOKEN V1 against a compatible corpus directory")
parser.add_argument("corpus", type=Path, help="Directory containing manifest.json and trajectory JSON files")
parser.add_argument("--output", type=Path, default=Path("benchmarks/results/rd0b-v1.json"))
args = parser.parse_args()
corpus = args.corpus.expanduser().resolve()
manifest = json.loads((corpus / "manifest.json").read_text())
cases = []
for item in manifest["trajectories"]:
    data = json.loads((corpus / item["file"]).read_text())
    blocks = []
    for turn in data["turns"]:
        for index, block in enumerate(turn["blocks"]):
            blocks.append(ContextBlock(id=f"t{turn['index']}-{index}-{block['id']}", kind=block["kind"], text=block["text"], role=block.get("role"), turn_index=turn["index"]))
    cases.append(BenchmarkCase(item["title"], RequestEnvelope(tuple(blocks))))

with tempfile.TemporaryDirectory() as tmp:
    engine = OptimizationEngine(planner=ContextPlanner(), store=RecoveryStore(Path(tmp) / "recovery.db"))
    report = benchmark_cases(cases, engine)

payload = {
    "corpus_cases": len(report.cases),
    "baseline_estimated_tokens": report.baseline_estimated_tokens,
    "optimized_estimated_tokens": report.optimized_estimated_tokens,
    "total_saved_pct": report.total_saved_pct,
    "eligible_saved_pct": report.eligible_saved_pct,
    "optimized_count": report.optimized_count,
    "bypass_count": report.bypass_count,
    "all_protected_fidelity": all(c.protected_byte_fidelity == 1.0 for c in report.cases),
    "all_recoverable": all(c.recoverable for c in report.cases),
    "reason_counts": {},
}
for case in report.cases:
    for reason in case.reasons:
        payload["reason_counts"][reason] = payload["reason_counts"].get(reason, 0) + 1
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, indent=2, sort_keys=True))
