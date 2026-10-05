# Contributing

## Ground rules

1. **Fixtures first.** If the change touches parsing, write or extend a
   synthetic fixture before touching the parser (TDD).
2. **Small commits.** One logical change per commit; describe *why*, not *what*.
3. **No live-database writes by default.** Treat Devin's stores as read-only
   unless the feature explicitly mutates them behind a flag.
4. **Platform docs.** Keep shared behavior in `README.md`; keep Windows and
   Linux setup, paths, commands, and troubleshooting in their OS-specific guides.

## Setup

```bash
pip install -e ".[dev]"
pytest
```

## Before opening a PR

- [ ] Tests pass on Windows and Linux (CI runs both).
- [ ] README sections *Prior art* and *Limitations* still accurate.
- [ ] CHANGELOG updated (semver).
- [ ] No secrets, tokens, or absolute user paths in code or docs.
