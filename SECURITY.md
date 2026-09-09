# TOKEN Security

TOKEN is designed as a local-first optimization runtime. The Alpha security contract is intentionally conservative.

## Network boundary

- The V1 gateway accepts only loopback bind hosts: `127.0.0.1`, `::1`, or `localhost`.
- TOKEN does not install a CA certificate and does not perform TLS MITM.
- Authorization headers are forwarded to the configured upstream because the upstream needs them, but TOKEN does not persist them.
- Unsupported endpoints and unsafe payload shapes are forwarded without optimization.

## Local data

The recovery store may contain byte-exact private prompt/context content removed from an optimized request. On POSIX systems, TOKEN enforces mode `0600` on recovery and metrics SQLite databases and on the JSON config.

Metrics use an allowlist schema. Arbitrary prompt/body/header/API-key fields are rejected rather than filtered after storage.

## Configuration mutation

Generic `.env` integration is bounded by TOKEN-managed begin/end markers. If an unmanaged `OPENAI_BASE_URL` already exists, installation is blocked rather than overwritten.

Codex integration transactionally changes only the selected provider `base_url`. TOKEN stores non-secret before/after hashes and the original provider URL, refuses ambiguous provider selection, and refuses uninstall if the managed config has drifted. A private pre-cutover config backup is retained for operational rollback.

Persistent uninstall does not keep a raw backup of `.env`. A TOKEN metadata sidecar stores only non-secret restoration metadata such as SHA-256 and whether TOKEN added a separator newline. Install and uninstall are fixture-tested for byte-equivalent restoration.

## Failure behavior

Optimization is fail-open to the **original request payload**: parse errors, unsafe wire shapes, planner bypasses, reducer failures, and optimizer exceptions do not produce a partially rewritten provider request.

Response payload bytes are proxied without content transformation.

## Current limitations

Alpha has not established universal live decision-equivalence, broad provider-cache non-regression, or native Anthropic/Gemini security boundaries. Those capabilities must not be advertised as certified.
