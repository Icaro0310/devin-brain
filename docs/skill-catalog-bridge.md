# skill-catalog bridge — `learned-*` drafts → `proposed` registry entries

`devin-learning extract` writes `learned-<topic>/SKILL.md` drafts;
`devin-skill-catalog` (the `devin-devkit` package) gates and promotes
items through `proposed → quarantined → approved → active → retired`.
`devin-learning catalog-bridge` closes the write side of that loop: it
scans a skills tree and registers each draft as a `proposed` item in the
catalog's own registry file, so the lifecycle commands can pick them up
without a manual first step.

```
extract --apply  →  catalog-bridge  →  devin-skill-catalog quarantine
 (write drafts)     (register                   --apply → G1/G3 gates →
                     as proposed)                promote → activate
```

## Usage

```bash
devin-learning catalog-bridge .devin/skills [--registry PATH] [--dry-run] [--json]
```

- `skills_dir` — a dir holding `learned-*/SKILL.md` (what
  `extract --out`/`--apply` produces). A `.devin` dir wrapping `skills/`
  is accepted too.
- `--registry` — defaults to
  `<config-dir>/.devin-ecosystem/skill-catalog.json`, resolved exactly
  like `devin-skill-catalog` (`DEVIN_CONFIG_DIR` wins, then the platform
  config dir).
- `--dry-run` — prints registered/updated/unchanged/skipped without
  writing.
- Exit codes: `0` success (including "no learned-* skills"), `3` on a
  malformed draft, missing skills dir, or unreadable/unwritable registry.

## Registry contract

The file is the one `devin_skill_catalog.registry.Registry` reads and
writes — same schema, same dump (`indent=2`, `sort_keys`, trailing
newline), same atomic write (tempfile in the registry dir + `os.replace`).
No dependency on the skill-catalog package is needed to honor the format.

```json
{
  "version": 1,
  "items": {
    "skill:learned-testing": {
      "kind": "skill",
      "name": "learned-testing",
      "state": "proposed",
      "sha256": "<sha256 of the SKILL.md file>",
      "origin": "<abs path of the .devin dir holding skills/>",
      "history": []
    }
  }
}
```

- Entries are **metadata only**: `sha256` identifies the content; draft
  bodies are never copied into the registry. `origin` lets the catalog
  re-locate the files for `quarantine` (it snapshots them into its own
  quarantine store).
- `proposed` is the catalog's registered-but-not-yet-vetted lane — the
  state every `quarantine` transition starts from.
- **Idempotent**: re-scanning an unchanged draft produces the same entry
  (byte-stable file). A re-scanned draft whose content changed gets
  `sha256`/`origin` refreshed in place while still `proposed`.
- **Lifecycle authority stays with the catalog**: entries already in
  `quarantined`/`approved`/`active`/`retired` are reported as skipped and
  never touched — a re-scan cannot silently un-vet an item in the gate
  pipeline. Entries for other kinds/names pass through verbatim.

## Draft validation

Before anything is written, every `learned-*/SKILL.md` must carry the
frontmatter the catalog's G1 lint treats as required — a failure names
the file and exits `3`:

- a `---` frontmatter block must be present;
- `name` must be set **and equal to the directory name**
  (`learned-<topic>`);
- `description` must be present and non-empty.

A `learned-*` directory with no `SKILL.md` is an error too. Non-`learned-*`
dirs are ignored — the bridge only handles learning-loop output.
