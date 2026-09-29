# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial scaffold from `devin-repo-template`.

## [0.1.0] - 2026-09-29

### Added

- `memory.db` store (`devin_memory.store`): own SQLite DB with
  `entries(id, content, tags, source_session_id, source_rowid, created_at,
  status, version, supersedes_id, quarantine_reasons)`; statuses
  `active` / `quarantined` / `retracted`.
- Quarantine gate (`devin_memory.screen`): vendored devin-redact-style
  secret regexes, injection heuristics, and size/shape limits; verdict +
  reasons stored on every suspect row.
- Ops (`devin_memory.ops`): `retain`, `recall` (active-only, deterministic
  keyword ranking), `retract`, `release`, `supersede` (versioned history),
  `list_entries`, `verify_provenance` — audits session id + message rowid
  against a real `sessions.db` via `devin-internals` (read-only).
- Export (`devin_memory.export`): `memories.jsonl` in the
  memory-MCP-compatible line shape with stable ids and optional
  provenance/version extras; active-only by default.
- `devin-memory` CLI: `retain` · `recall` · `quarantine` · `retract` ·
  `supersede` · `list` · `export` · `verify`; `--db` / `DEVIN_MEMORY_DB`.
- `docs/SPEC.md`, bilingual READMEs, STATUS.md.
- Depends on `devin-internals-spec` v0.2.0 (git tag).
