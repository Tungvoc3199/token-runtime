# TOKEN Alpha Verification Status

## Public status

TOKEN `v0.1.0-alpha.1` is an alpha release. The runtime is deterministic, local-first, and designed to bypass requests when optimization is not considered safe.

## Verified source checks

- Full unit suite: 72/72 PASS at the public-ready release commit.
- Python 3.12 and 3.13 GitHub Actions: package install, unit tests, compile check, import/CLI smoke, and whitespace gate PASS.
- Runtime source under `src/token_runtime/` is unchanged by the public packaging checkpoint.

## Offline benchmark evidence

On the 64-workload evaluation corpus used for the alpha gate:

- optimized cases: 40/64
- deliberately bypassed cases: 24/64
- eligible-workload estimated saving: 28.53%
- overall corpus estimated saving: 10.61%
- protected-byte fidelity: 100%
- recovery-reference resolution: 100%

These are bounded evaluation results, not a universal quality or billed-cost guarantee.

## Live paired evidence

A paired live example reduced reported input from 6,975 to 3,927 tokens (43.70%) with identical expected output. A separate bounded live campaign exposed a structured-decision regression class; the final alpha policy responds by bypassing that class unchanged.

## Claim boundary

TOKEN does not claim zero regression for every workload, universal token reduction, guaranteed provider-billing savings, or native Anthropic/Gemini support. Multimodal optimization is disabled in this alpha and unsupported shapes pass through.

## Privacy and rollback

Prompt bodies, authorization headers, API keys, and arbitrary request content are not persisted as metrics. Install/uninstall operations are hash-guarded and rollback-aware; user-specific machine paths, backups, and internal operational metadata are intentionally excluded from this public repository.
