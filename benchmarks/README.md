# TOKEN Public Benchmark

The public corpus is synthetic, non-sensitive, deterministic, and intended to prove safety invariants rather than universal savings.

Covered classes:
- repeated assistant history eligible for deterministic reduction;
- repeated historical tool output with latest evidence protected;
- active/latest user text protected byte-faithfully;
- structured decision context bypass;
- exact-edit context bypass;
- ambiguous decision-like context bypass.

Run:

```bash
PYTHONPATH=src python3 benchmarks/run_rd0b_offline.py benchmarks/public-corpus --output /tmp/token-public-v1.json
cmp /tmp/token-public-v1.json benchmarks/results/public-v1.json
```

`benchmarks/results/public-v1.json` is frozen evidence for this corpus generation. It is not a claim about every workload, provider bill, or model-quality outcome.
