# TOKEN Compatibility Matrix

This document describes the compatibility evidence present in the canonical TOKEN source.
It does not imply that every installed or deployed TOKEN gateway is running the same generation.

## Status vocabulary

- **SUPPORTED** — available on the production OpenAI-compatible gateway path described by the current public docs.
- **CERTIFIED** — a version- and boundary-specific compatibility record is backed by explicit evidence. It is not a universal quality, cache, billing, or provider guarantee.
- **PASSTHROUGH_ONLY** — TOKEN preserves that boundary unchanged instead of applying optimization semantics to it.
- **Implemented, not deployed** — canonical source contains the adapter/conformance code, but the production gateway does not route that native protocol.

## Production gateway surface

| Integration | Status | Boundary |
|---|---|---|
| OpenAI Responses API, text payloads | SUPPORTED | OpenAI-compatible local gateway |
| OpenAI Chat Completions, text payloads | SUPPORTED | OpenAI-compatible local gateway |
| Codex with selected OpenAI-compatible provider config | SUPPORTED | Transactional `base_url` integration with drift guards |
| Generic clients honoring `OPENAI_BASE_URL` | SUPPORTED | OpenAI-compatible local gateway |
| Multimodal optimization | PASSTHROUGH_ONLY | Unsupported wire shapes remain unchanged |

## Canonical compatibility evidence

| Capability | State | Evidence boundary |
|---|---|---|
| Codex CLI 0.154.0 / Responses request-response boundary | CERTIFIED | Exact request replay, opaque response forwarding, TOKEN OFF/ON boundary, resume/fork continuity |
| Anthropic Messages adapter/conformance | PASSTHROUGH_ONLY | Offline request-boundary conformance; implemented but not wired into the production gateway |
| Gemini GenerateContent adapter/conformance | PASSTHROUGH_ONLY | Offline request-boundary conformance; implemented but not wired into the production gateway |

### Codex 0.154.0 boundary detail

The overall Codex 0.154.0 Responses boundary is `CERTIFIED`, but certification is intentionally narrow.
The following areas remain `PASSTHROUGH_ONLY` because TOKEN does not own or fully observe those native semantics:

- native context compaction;
- authorization state across compaction;
- long-context compaction semantics;
- dynamic plugin/skill refresh;
- MCP OAuth and rejected-tool-call no-replay behavior;
- provider prompt/server cache and billing semantics.

This split is deliberate. A certified request boundary must not be broadened into claims about internal client state that TOKEN cannot observe.

## Anthropic and Gemini boundary

The canonical source includes native request adapters plus offline conformance suites for Anthropic Messages and Gemini GenerateContent.
Both compatibility records remain `PASSTHROUGH_ONLY`, and neither adapter is wired into the production gateway.

Therefore public wording may say that adapter/conformance support exists in canonical development, but must not say that native Anthropic or Gemini production routing is enabled or certified.

## Canonical source versus installed runtime

Repository capabilities and deployed capabilities are separate facts. Before making a runtime claim, verify the installed gateway generation and its active configuration rather than inferring deployment from files present in the repository.

## Claim boundary

Compatibility evidence is not permission to claim universal token savings, universal quality non-regression, billed-currency savings, or broad cache non-regression. Performance claims remain governed by [`docs/CLAIMS.md`](CLAIMS.md).
