---
name: devin-brain
description: "Durable, anti-poisoning memory for Devin: retain what was learned in a session and recall it when starting related work. Write path is gated — entries flagged as secret/injection land in quarantine automatically. Human review operations stay CLI-only."
triggers: [model, user]
allowed-tools:
  - exec
  - read
---

# devin-brain

When this plugin's MCP server is connected, use the memory tools:

- `retain(content, tags?, workspace?, source_session?)` — store a
  durable memory. The quarantine gate runs on every write; flagged
  entries never reach recall.
- `recall(query?, limit?, tags?)` — keyword-ranked recall over active
  memories only.
- `screen(content, tags?)` — dry-run the gate: shows the status retain
  would produce without writing.
- `list(status?, limit?)` — list entries by status.
- `conflicts()` — show conflicting memory pairs.
- `prime(workspace?, max_tokens?)` — context block of relevant memories
  for the current workspace.
- `verify(entry_id, sessions_db)` — check an entry's provenance.

Typical flow: `prime` or `recall` when starting a task; `retain` when
you learned something durable (a decision, a gotcha, a convention).

## Rules

- Never `retain` secrets, tokens, or credentials — the gate will
  quarantine them anyway; do not try to bypass it.
- Review operations are **not** part of this surface: `approve`,
  `retract`, `supersede`, `quarantine`, `release` and `extract` stay
  CLI-only, for a human to run deliberately (the plugin launches the
  server with `--read-only`, so those tools are not even registered):

  ```bash
  devin-memory list --status proposed     # pending review
  devin-memory list --status quarantined  # flagged by the gate
  devin-memory approve <id>               # promote to active
  devin-memory quarantine --release <id>  # human override back to active
  ```

- Prefer `screen` before `retain` when unsure whether content is
  store-worthy.
