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
