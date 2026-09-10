# TOKEN Claims Registry

This registry is the evidence boundary for externally visible TOKEN performance and quality claims. Public wording must not exceed the evidence, scope, and limitations recorded here.

## C-001 — Paired live workload input reduction

- **Evidence:** One paired live workload measured 6,975 input tokens without TOKEN and 3,927 with TOKEN, a 43.70% input-token reduction. The expected answer was correct in both runs.
- **Scope:** One paired workload on the verified Alpha route and configuration used for that experiment.
- **Limitations:** This is not evidence of universal savings, universal quality non-regression, billed-currency savings, broad provider-cache non-regression, or unrelated client/protocol behavior.
- **Allowed wording:** "In one paired live workload, TOKEN reduced measured input tokens from 6,975 to 3,927 (43.70%) while preserving the expected answer."

## C-002 — Frozen 64-workload offline benchmark

- **Evidence:** The frozen 64-workload offline benchmark measured 28.53% estimated saving across eligible workloads and 10.61% estimated saving across the full corpus. Protected-byte fidelity and recovery-reference resolution were 100% in that benchmark.
- **Scope:** The frozen 64-workload offline corpus and its benchmark generation only.
- **Limitations:** These estimated input-token results are not universal quality, universal savings, billed-currency savings, provider-cache guarantees, native Anthropic certification, or native Gemini certification.
- **Allowed wording:** "On the frozen 64-workload offline corpus, TOKEN measured 28.53% estimated saving on eligible workloads and 10.61% across the full corpus, with 100% protected-byte fidelity and recovery-reference resolution."

## Prohibited promotion

Do not convert bounded evidence into wording such as "saves 43.70% on every request", "guarantees no quality regression", "cuts API bills by 43.70%", or any other universal or currency-savings claim not supported by a separately registered claim.
