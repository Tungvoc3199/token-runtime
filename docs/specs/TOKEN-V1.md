# TOKEN V1 Product Spec

Date: 2026-09-09
Status: Alpha active architecture after TOKEN-R&D-0A/0B/0C and Codex live certification

## Goal

TOKEN is a local-first adaptive context optimization runtime that reduces unnecessary LLM input while preserving task behavior. It must prefer exact passthrough over risky optimization.

## Product contract

- Install once; supported clients continue using their normal workflow.
- Do not change the user's provider or model.
- Do not log prompt bodies, API keys, or private payloads by default.
- Do not use TLS MITM.
- Unsupported or risky requests pass through byte-equivalent at the provider payload boundary.
- Quality is the primary KPI; token/cost savings are secondary.
- Raw removed content is locally recoverable when reversible reduction is used.
- Cache-sensitive stable prefixes must not be rewritten by default.

## R&D evidence

TOKEN-R&D-0C reduced live input from 90,574 to 63,807 tokens (29.55%) across eight cases, but one baseline-stable case regressed. The expected fact was still visible, proving that fact retention and byte recoverability alone do not guarantee decision equivalence. Therefore candidate v0 is blocked and V1 requires a behavior-preservation planner.

The final V1 deterministic planner/reducer stack was rerun offline on 64 trajectories without reading hidden grading labels. It reduced estimated input from 1,425,422 to 1,274,139 tokens overall (10.61%), while the 40 eligible optimized cases achieved 28.53% estimated savings and 24 structured decision-risk cases bypassed unchanged. Protected-byte fidelity and recovery-reference resolution both remained 100%. This is an offline safety/efficiency gate, not a universal claim of live decision-equivalence.

## Architecture

Request -> integration adapter -> normalized context -> risk classifier -> context planner -> optimization ladder -> telemetry -> provider.

The planner classifies each request as BYPASS or OPTIMIZE. OPTIMIZE may use only registered deterministic reducers in V1. Semantic/LLM compression is out of the default path until separately certified.

### Protected context

The planner preserves system/developer instructions, current user instruction, tool schemas and protocol identifiers, current/latest tool evidence, explicit hard constraints, active decisions, exact-edit source, code diffs, critical error literals, and ambiguous competing decision state.

### Salience guard

The complete latest turn is byte-protected. Multiple distinct non-protocol `DECISION:` anchors inside the active/latest turn force BYPASS, as do exact-edit material and unsupported wire shapes. Historical decision anchors remain protected but do not automatically block the whole request; deterministic reduction may still operate on unrelated old context. This policy was introduced after the globally-conservative rule produced 0% savings on the 64-trajectory corpus.

### Optimization ladder

- L0: exact passthrough / cache preservation.
- L1: exact duplicate removal and repeated-line collapse where structurally safe.
- L2: deterministic old tool/log compaction with all decision/error/constraint anchors retained.
- L3: reversible archival of eligible large retrieved blocks with explicit local references.
- L4 semantic compression is disabled in V1.

## Interfaces

Core input is a normalized `RequestEnvelope` containing ordered `ContextBlock` values plus opaque provider fields. Core output is `OptimizationResult` with decision, transformed envelope, savings metrics, risk/bypass reasons, and recovery metadata.

Provider adapters are responsible only for lossless parse/serialize. The core never knows Codex, Claude, or a provider-specific wire format.

The first wire adapters are OpenAI Responses and Chat Completions. Other providers plug into the same normalized interface.

## Gateway safety

The local gateway forwards authorization headers without persisting them. On parse, planning, optimization, or internal failure it sends the original request unchanged. Streaming response bytes are proxied without transformation.

## Installer contract

`token install` is transactional: detect -> plan -> snapshot managed fields -> apply -> verify. `token uninstall` restores only fields TOKEN owns. V1 must include dry-run and fixture-tested Codex/OpenAI-compatible detection before touching a real client config.

## Telemetry

Local metrics record counts, provider/model labels when available, input/output/cache token usage, optimization decision, estimated before/after input, latency, reducer IDs, and bypass/fallback reason. Prompt bodies and credentials are excluded.

## Verification gates

Offline gates before another paid live run:
- protected blocks byte-identical;
- competing-decision cases bypass;
- risky/unsupported cases exact passthrough;
- reversible store round-trips byte-exact;
- provider parse/serialize preserves untouched fields;
- gateway failure path forwards original payload;
- no secrets or prompt bodies in telemetry;
- full unit/integration suite green;
- R&D corpus benchmark reports savings only for eligible cases.

Live promotion gate requires separate authorization and A/A/B evaluation. It requires zero observed critical regressions on the pilot set, statistically non-inferior task success on a larger corpus, >=20% real savings on eligible workload, no protocol corruption, and no proven cache regression.

## Non-goals for V1

- Transparent HTTPS interception.
- Claiming support for every application.
- Automatic provider/model routing.
- Cloud telemetry.
- Lossy semantic compression by default.
- Production mutation of unrelated external runtimes or user configuration during development.
