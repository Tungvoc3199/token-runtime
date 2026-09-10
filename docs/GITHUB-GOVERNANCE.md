# TOKEN GitHub Governance

This document defines the public repository governance baseline for `token-runtime`.
The private canonical source remains authoritative; public GitHub is a release and
contribution-intake channel.

## Main branch protections

The public `main` branch must:

- block force-push;
- block deletion;
- require CI before merge;
- require a pull request for external contributor changes.

These controls protect release integrity without turning the public repository into a
second canonical development source.

## Maintainer release lane

Maintainers retain a bounded release lane for deterministic private-to-public sync.
That lane may publish only a candidate that has passed the release qualification gates:
classification, public audit, deterministic export, runtime digest equivalence, and CI.

Direct feature development in the public repository is not the release lane. Accepted
public contributions flow through the contribution bridge and are verified in private
canonical before appearing in a later sanitized public sync.

## Owner-controlled mutation

Changing GitHub rulesets, branch protection, repository visibility, public `main`, tags,
or releases is an owner-controlled action. Documentation or a passing test suite does not
authorize those repository mutations implicitly.
