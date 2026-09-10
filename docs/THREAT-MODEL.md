# TOKEN Threat Model

## System and trust boundaries

The normal data path is:

```text
client -> TOKEN gateway -> upstream
```

The client sends a request to the loopback TOKEN gateway. TOKEN may use a local recovery store for reversible transformations. The upstream remains the configured provider or compatible gateway; TOKEN does not silently switch providers or models.

Primary trust boundaries are:
- the **client** process and its request data;
- the loopback **TOKEN gateway** process;
- the configured **upstream** service and network path;
- the local **recovery store**, which may contain byte-exact private context;
- configuration files and generated public release artifacts.

## Protected assets

- prompt, context, tool-output, and recovery bytes;
- authorization-header transit data and API credentials;
- integration configuration and rollback metadata;
- release source integrity and public/private classification;
- benchmark evidence used for public claims.

## Assumptions

TOKEN assumes the local operating-system account, kernel, Python runtime, and configured upstream are not already compromised. A compromised local account can read local process memory and files and is outside the Alpha protection boundary.

The gateway is designed for loopback binding. Exposing the gateway beyond loopback is not a certified deployment mode.

## Threats and controls

### Prompt or recovery-data leakage
Recovery data is local, byte-sensitive, and must not be emitted to telemetry, logs, public artifacts, or release metadata. Metrics use an allowlist rather than post-hoc filtering.

### Credential leakage
Authorization headers may transit the gateway because the upstream needs them, but TOKEN does not persist them. Public-release audit gates reject high-confidence credential patterns.

### Unsafe configuration mutation
Managed configuration edits are bounded and rollback-aware. Ambiguous ownership or drift must fail closed rather than overwrite unrelated settings.

### Malformed or unknown wire shapes
Unsupported, malformed, multimodal, or semantically unknown shapes take the conservative exact-passthrough path when forwarding is safe. TOKEN must not guess fields away.

### Optimizer failure
Parser, planner, reducer, or optimizer failure returns the original request path rather than a partially rewritten request.

### Public-release leakage
Every tracked file in a release candidate is classified public or private. Unclassified or ambiguous paths block export. Generated public candidates are audited for secrets, private paths, private-repository references, and forbidden internal names before qualification.

## Non-goals

This threat model does not claim protection from a compromised local operating system, compromised user account, malicious Python runtime, malicious upstream, or physical-access attacker with equivalent privileges.
