# Contributing to TOKEN

TOKEN welcomes focused, test-backed contributions that preserve its safety-first context contract.

## Development flow

1. Fork or branch from the public `token-runtime` repository.
2. Install the development environment described below.
3. Add or update tests before implementation when behavior changes.
4. Run the documented quality gates.
5. Open a public pull request with the problem, scope, tests, and risk notes.

## Contribution bridge

`token-runtime` is the public pull request and release channel. The maintainer reviews accepted public changes, ports the accepted patch into the private canonical source, runs canonical verification, and only then includes the change in the next sanitized public sync. The public repository is not an independent canonical development branch.

## Scope rules

- Preserve exact passthrough for unsafe or unknown context.
- Do not add provider/model switching.
- Do not add prompt, header, credential, or recovery-content telemetry.
- Do not weaken tests to make a change pass.
- Keep runtime dependencies at zero unless a separately approved checkpoint changes that contract.

## Development setup

```bash
python -m pip install -e '.[dev]' --no-build-isolation
```

## Verification

Run the same bounded gates used by CI:

```bash
ruff check src tests scripts benchmarks
coverage run -m unittest -q
coverage report --fail-under=80
python -m compileall -q src tests scripts benchmarks
python scripts/public_audit.py --source-tree .
```

Release-candidate export, digest-equivalence, and owner-controlled publication gates are documented in `docs/RELEASE-PROCESS.md`.
