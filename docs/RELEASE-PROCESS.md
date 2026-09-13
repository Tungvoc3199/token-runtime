# TOKEN Release Process

TOKEN has one private canonical development source and a generated public release channel. The public channel must never become an independent source of truth.

## Promotion ladder

```text
private RC
-> deterministic export
-> fail-closed public audit
-> runtime digest equivalence
-> public CI
-> owner-approved release
-> post-release verification
```

A later gate never substitutes for a missing earlier gate.

## Private RC

A release candidate starts from one fresh canonical commit and a clean source tree. Relevant unit, safety, regression, lint, compile, and benchmark gates must already be green.

## Deterministic export

The exporter classifies every tracked path as public or private, copies public bytes in deterministic path order, and emits only public-safe provenance. The same source and release version must produce byte-identical candidates.

Generated release metadata contains deterministic digests and version data only. It must not include a private commit SHA, machine path, author email, wall-clock timestamp, or internal infrastructure name.

## Audit and equivalence

The candidate must have zero secret/privacy/internal-name findings. Its `src/token_runtime` tree digest must match the canonical runtime digest exactly. Runtime digest equivalence is mandatory because source-only tests do not prove artifact identity.

## Public CI and release

The generated candidate runs public CI before an owner-approved release. Repository ruleset changes, public synchronization, release publication, and package publication are explicit owner actions.

## Contribution bridge

A public pull request is reviewed in the public channel. An accepted patch is ported into the private canonical source, canonical verification is run there, and the next deterministic sanitized public sync carries the verified result outward.

## Post-release verification

After an approved public mutation, verify the public `main` identity, CI state, audit state, release files, and expected visibility. Confirm that the private canonical source changed only through approved commits and that locked Golden refs remain unchanged.

## Distribution qualification

C4 qualifies `token-runtime` from a sanitized public candidate only. Release labels use the strict mapping `vX.Y.Z-alpha.N -> X.Y.ZaN`; the current candidate is `v0.1.0-alpha.2 -> 0.1.0a2`.

Build qualification uses `SOURCE_DATE_EPOCH=1788998400`, a controlled build backend, and two independent sanitized candidates. The wheel and sdist must compare byte-for-byte before a reproducibility claim is allowed. The verified bundle contains `release/dist/`, `release/SHA256SUMS`, and `release/TOKEN_DISTRIBUTION_PROVENANCE.json`.

Local qualification verifies the bundle, installs the wheel and sdist into disposable virtual environments, runs `uv tool` from disposable state, and proves `0.1.0a1 -> 0.1.0a2 -> 0.1.0a1` upgrade/rollback. It never uses an editable install and never runs `token install` or `token uninstall` against user state.

The distribution workflow builds and qualifies local artifacts only. Index-backed user commands are post-publication instructions and are not executed by C4 before the owner gate:

```text
python -m pip install token-runtime
uv tool install token-runtime
```

## PyPI Trusted Publishing

`publish-pypi.yml` is manual only. `publish=false` is the default and performs verification without upload. The requested qualification run must be successful and its `head_sha` must equal the dispatch commit; a publish run additionally requires the dispatch ref to equal the provenance release tag.

Only the conditional publish job receives `id-token: write`, and it runs in the protected `pypi` environment. It downloads the already-qualified bytes, rechecks their hashes, and publishes `release/dist` without checkout or rebuilding. Authentication is PyPI Trusted Publishing via short-lived OIDC; no username, password, API token, or long-lived PyPI secret is used.

`TOKEN_DISTRIBUTION_PROVENANCE.json` is deterministic pre-publication provenance. PyPI publish-time attestations are separate, complementary evidence and remain enabled by default.
