# LLM Change Playbook

This playbook defines the safe update path when an LLM, client version, provider identity, or wire protocol changes. Protocol selection and capability/certification are separate contracts: endpoint routing chooses an adapter, while exact capability/evidence identity determines whether TOKEN may optimize or must remain `PASSTHROUGH_ONLY`.

## Decision Table

| Change | Required TOKEN work | Core change? | Production routing? |
| --- | --- | --- | --- |
| Model/version only; wire protocol unchanged | Exact capability identity + conformance/certification evidence + compatibility record | **No** routine gateway/engine/planner/reducer change | **No** until separately owner-approved |
| New wire protocol with requested runtime support | Dedicated adapter + round-trip/conformance tests + registry work + separate capability/evidence work | Only the adapter/registry boundary unless a separately approved Core semantic change is required | **No** until separately owner-approved |
| New protocol identity with conformance-only scope and no runtime-support request | Exact capability identity + frozen evidence + `PASSTHROUGH_ONLY` compatibility record; **no adapter and no route** | **No** | **No** |
| Unknown, uncertified, or evidence-mismatched identity | Preserve exact passthrough safety and classify `PASSTHROUGH_ONLY` | **No** | **No** |

## Recipe A: Model or Version Change With Unchanged Protocol

1. Identify the exact `client + protocol + provider + model/version` identity. Do not infer support from a similar name or nearby version.
2. Keep the existing protocol adapter unchanged when the wire semantics are unchanged.
3. Produce or update conformance and certification evidence for the exact identity.
4. Register the exact capability profile and compatibility record using the evidence identity required by the current certification contract.
5. Run exact-key and near-key regressions. Unknown identities, missing profiles, unknown compatibility, and evidence mismatches must remain `PASSTHROUGH_ONLY`.
6. Promote only to the compatibility state justified by evidence; do not auto-promote from a family name or semantic similarity.
7. Do **not** change TOKEN Core (`gateway`, `engine`, `planner`, or reducers) merely because a model or client version string changed.
8. Do **not** change production routing, provider, model, or runtime configuration until that operational change is separately owner-approved.

### Expected files for a routine model/version update

Typical changes belong in capability/evidence/certification data and their focused tests. If the wire protocol is unchanged, an edit to `GatewayCore`, `ProtocolAdapterRegistry`, engine, planner, or reducers is a signal to re-check scope before proceeding.

## Recipe B: New Protocol With Requested Runtime Support

1. Define the new wire contract and the dedicated adapter's parse/serialize behavior.
2. Add round-trip and conformance tests before implementation so unsupported or opaque fields remain protected by the adapter contract.
3. Implement the dedicated adapter and register its endpoint/factory in `ProtocolAdapterRegistry`.
4. Keep capability/evidence registration separate from protocol selection. The registry must select only from the request endpoint/path and must not inspect model, provider, capability state, or client version.
5. Verify unknown endpoints and malformed or unsupported shapes still fall back safely without mutating the raw request body.
6. Run focused adapter/gateway tests, capability/compatibility regressions, the full suite, Ruff, compileall, public audit, and `git diff --check`.
7. Do **not** edit engine/planner/reducers unless a separately approved Core semantic change is genuinely required by the new protocol rather than by its name.
8. Do **not** route production traffic to the new protocol until production routing is separately owner-approved.

## Recipe C: New Protocol Identity, Conformance Only

1. Freeze the exact protocol/capability identity and external schema/documentation snapshot.
2. Build offline synthetic conformance evidence for only the observed/tested boundary.
3. Bind tested shapes, exact corpus bytes/order, assertions, and snapshot metadata into the evidence identity.
4. Register the exact capability and canonical compatibility record as `PASSTHROUGH_ONLY`; do not attach certified benchmark-generation semantics.
5. Keep native state opaque and prefer native provider/client context management when TOKEN has no certified transformation boundary.
6. Prove exact-key isolation and that an enabled TOKEN feature flag still cannot produce execution for the passthrough-only identity.
7. Keep the protocol registry and gateway unchanged when runtime support was not requested; unknown endpoint handling remains exact raw-body passthrough.
8. Treat later runtime routing as a separate architecture checkpoint rather than silently upgrading conformance evidence into an adapter.

## Registry Contract

The default protocol registry preserves the existing endpoints:

- `/v1/responses` -> `ResponsesAdapter`
- `/v1/chat/completions` -> `ChatCompletionsAdapter`

Query strings are ignored for endpoint resolution. Registering the same normalized endpoint more than once is rejected rather than silently replacing the existing adapter. An unknown endpoint resolves to no adapter, so the gateway keeps the exact raw request body and records `unsupported_endpoint`.

## Safety Rules

- Protocol selection is endpoint-only.
- Capability and compatibility resolution is exact-keyed.
- Similar model names or adjacent client versions do not inherit certification.
- Unknown or uncertified identities remain `PASSTHROUGH_ONLY`.
- TOKEN Core stays model-identifier agnostic.
- Production routing remains unchanged until separately owner-approved.
