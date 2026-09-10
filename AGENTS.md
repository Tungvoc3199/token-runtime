# TOKEN Agent Instructions

These instructions are public-safe and apply to automated coding agents working on TOKEN.

- Read the active task and relevant tests before editing.
- Preserve unrelated work.
- Use a clean isolated branch or worktree for mutations.
- Prefer test-first changes for behavior.
- Keep changes within the requested checkpoint.
- Never print or persist credentials, private prompt content, authorization headers, or recovery payloads.
- Never change provider/model routing, publish releases, or mutate deployment state unless the task explicitly authorizes it.
- Verify targeted tests, relevant regression, and static gates before claiming completion.
- Treat exact passthrough and rollback behavior as product invariants.
