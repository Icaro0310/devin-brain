"""catalog-bridge: learned-* drafts → skill-catalog `proposed` entries.

The registry format mirrors devin_skill_catalog.registry — a single JSON
file ``{"version": 1, "items": {"skill:<name>": {...}}}`` written
atomically. Tests here only ever use tmp fixtures: no real registry, no
real .devin dir is touched.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from devin_memory.learning import cli
from devin_memory.learning.catalog_bridge import (
    CatalogBridgeError,
    bridge,
    default_registry_path,
    load_registry,
)


def _write_skill(
    skills_root,
    name,
    *,
    frontmatter: str | None = None,
    body: str = "\n# Lessons\n\n- a lesson\n",
) -> str:
    """Write ``<skills_root>/<name>/SKILL.md``; returns the file path."""
    d = skills_root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = frontmatter
    if fm is None:
        fm = (
            f"name: {name}\n"
            f'description: "Lessons about {name} auto-extracted '
            'from Devin sessions"\n'
        )
    path = d / "SKILL.md"
    path.write_text(f"---\n{fm}---{body}", encoding="utf-8")
    return str(path)


def _registry(tmp_path):
    return tmp_path / "cfg" / ".devin-ecosystem" / "skill-catalog.json"


def _run(skills_dir, registry, *extra):
    return cli.main(
        ["catalog-bridge", str(skills_dir), "--registry", str(registry),
         *extra]
    )


def _items(registry_path):
    return json.loads(registry_path.read_text(encoding="utf-8"))["items"]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_registers_proposed_entries(tmp_path, capsys):
    skills = tmp_path / "skills"
    md = _write_skill(skills, "learned-testing")
    _write_skill(skills, "learned-docs")
    registry = _registry(tmp_path)

    assert _run(skills, registry) == 0
    out = capsys.readouterr().out
    assert "+ skill:learned-testing" in out
    assert "+ skill:learned-docs" in out

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["version"] == 1
    items = data["items"]
    assert set(items) == {"skill:learned-testing", "skill:learned-docs"}
    entry = items["skill:learned-testing"]
    assert entry["kind"] == "skill"
    assert entry["name"] == "learned-testing"
    assert entry["state"] == "proposed"
    assert entry["sha256"] == _sha(__import__("pathlib").Path(md))
    assert entry["origin"] == str(tmp_path.resolve())
    assert entry["history"] == []
    # the registry stores metadata only — never the draft body
    assert "a lesson" not in registry.read_text(encoding="utf-8")


def test_devin_dir_argument_resolves_skills_subdir(tmp_path):
    devin = tmp_path / ".devin"
    _write_skill(devin / "skills", "learned-x")
    registry = _registry(tmp_path)

    report = bridge(devin, registry)
    assert report["registered"] == ["learned-x"]
    entry = _items(registry)["skill:learned-x"]
    assert entry["origin"] == str(devin.resolve())


def test_idempotent_rescan_is_byte_stable(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    registry = _registry(tmp_path)

    assert _run(skills, registry) == 0
    first = registry.read_bytes()
    capsys.readouterr()
    assert _run(skills, registry) == 0
    out = capsys.readouterr().out
    assert "= skill:learned-testing" in out
    assert registry.read_bytes() == first  # no dup, no churn


def test_changed_draft_refreshes_sha(tmp_path):
    skills = tmp_path / "skills"
    md = _write_skill(skills, "learned-testing")
    registry = _registry(tmp_path)
    assert _run(skills, registry) == 0
    old_sha = _items(registry)["skill:learned-testing"]["sha256"]

    with open(md, "a", encoding="utf-8") as fh:
        fh.write("- another lesson\n")
    assert _run(skills, registry) == 0
    entry = _items(registry)["skill:learned-testing"]
    assert entry["state"] == "proposed"
    assert entry["sha256"] != old_sha
    assert entry["sha256"] == _sha(__import__("pathlib").Path(md))


def test_deterministic_ordering(tmp_path, capsys):
    skills = tmp_path / "skills"
    for name in ("learned-zeta", "learned-alpha", "learned-mid"):
        _write_skill(skills, name)
    registry = _registry(tmp_path)
    assert _run(skills, registry) == 0
    out = capsys.readouterr().out
    order = [
        line.split("skill:")[1].split()[0]
        for line in out.splitlines()
        if "skill:" in line
    ]
    assert order == ["learned-alpha", "learned-mid", "learned-zeta"]
    # registry keys sort identically (json.dump sort_keys)
    assert list(_items(registry)) == [
        "skill:learned-alpha",
        "skill:learned-mid",
        "skill:learned-zeta",
    ]


def test_ignores_non_learned_dirs(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    _write_skill(skills, "hand-written-skill")  # not learned-* → ignored
    registry = _registry(tmp_path)
    assert _run(skills, registry) == 0
    assert set(_items(registry)) == {"skill:learned-testing"}


# ---------------------------------------------------------------------------
# lifecycle authority — non-proposed entries are never clobbered
# ---------------------------------------------------------------------------


def test_skips_entries_past_proposed(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    _write_skill(skills, "learned-docs")
    registry = _registry(tmp_path)
    registry.parent.mkdir(parents=True)
    quarantined = {
        "kind": "skill",
        "name": "learned-testing",
        "state": "quarantined",
        "sha256": "cafe",
        "origin": "/elsewhere/.devin",
        "store": "/cfg/.devin-ecosystem/skill-catalog/quarantine/skill/learned-testing",
        "gates": {"g1": {"status": "pass", "at": "2026-10-20T00:00:00Z"}},
        "history": [
            {
                "at": "2026-10-20T00:00:00Z",
                "from": "proposed",
                "to": "quarantined",
                "note": "review",
            }
        ],
    }
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "items": {
                    "skill:learned-testing": quarantined,
                    "rule:house-style": {
                        "kind": "rule",
                        "name": "house-style",
                        "state": "active",
                        "history": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    assert _run(skills, registry) == 0
    out = capsys.readouterr().out
    assert "! skill:learned-testing  skipped (state=quarantined)" in out
    items = _items(registry)
    # the catalog-owned entry and the unrelated rule survive verbatim
    assert items["skill:learned-testing"] == quarantined
    assert items["rule:house-style"]["state"] == "active"
    # the second draft still lands as proposed
    assert items["skill:learned-docs"]["state"] == "proposed"


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    registry = _registry(tmp_path)

    assert _run(skills, registry, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "+ skill:learned-testing" in out
    assert not registry.exists()


def test_dry_run_leaves_existing_registry_alone(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    registry = _registry(tmp_path)
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"version": 1, "items": {}}), encoding="utf-8"
    )
    before = registry.read_bytes()
    report = bridge(skills, registry, dry_run=True)
    assert report["registered"] == ["learned-testing"]
    assert registry.read_bytes() == before


# ---------------------------------------------------------------------------
# malformed drafts — fail loudly, naming the file
# ---------------------------------------------------------------------------


def test_missing_name_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    md = _write_skill(
        skills, "learned-x", frontmatter='description: "no name here"\n'
    )
    assert _run(skills, _registry(tmp_path)) == 3
    err = capsys.readouterr().err
    assert md in err and "name" in err


def test_missing_description_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    md = _write_skill(skills, "learned-x", frontmatter="name: learned-x\n")
    assert _run(skills, _registry(tmp_path)) == 3
    err = capsys.readouterr().err
    assert md in err and "description" in err


def test_no_frontmatter_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    d = skills / "learned-x"
    d.mkdir(parents=True)
    md = d / "SKILL.md"
    md.write_text("# no frontmatter at all\n", encoding="utf-8")
    assert _run(skills, _registry(tmp_path)) == 3
    assert str(md) in capsys.readouterr().err


def test_name_must_match_directory(tmp_path, capsys):
    skills = tmp_path / "skills"
    md = _write_skill(
        skills,
        "learned-x",
        frontmatter='name: learned-other\ndescription: "mismatch"\n',
    )
    assert _run(skills, _registry(tmp_path)) == 3
    err = capsys.readouterr().err
    assert md in err and "learned-other" in err


def test_learned_dir_without_skill_md_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    orphan = skills / "learned-broken"
    orphan.mkdir(parents=True)
    assert _run(skills, _registry(tmp_path)) == 3
    assert "learned-broken" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# registry errors + edge cases
# ---------------------------------------------------------------------------


def test_empty_dir_is_clean_exit(tmp_path, capsys):
    skills = tmp_path / "skills"
    skills.mkdir()
    registry = _registry(tmp_path)
    assert _run(skills, registry) == 0
    assert "no learned-* skills" in capsys.readouterr().out
    assert not registry.exists()


def test_missing_skills_dir_fails(tmp_path, capsys):
    assert _run(tmp_path / "nope", _registry(tmp_path)) == 3
    assert "nope" in capsys.readouterr().err


def test_corrupt_registry_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-x")
    registry = _registry(tmp_path)
    registry.parent.mkdir(parents=True)
    registry.write_text("{not json", encoding="utf-8")
    assert _run(skills, registry) == 3
    assert "skill-catalog.json" in capsys.readouterr().err


def test_wrong_shape_registry_fails(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-x")
    registry = _registry(tmp_path)
    registry.parent.mkdir(parents=True)
    registry.write_text('{"version": 1, "items": []}', encoding="utf-8")
    with pytest.raises(CatalogBridgeError, match="unexpected shape"):
        bridge(skills, registry)


def test_unwritable_registry_fails(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-x")
    # a directory where the registry file should be — portable across
    # platforms (no chmod tricks needed on Windows CI)
    registry = tmp_path / "skill-catalog.json"
    registry.mkdir()
    assert _run(skills, registry) == 3
    assert "skill-catalog.json" in capsys.readouterr().err


def test_json_report_shape(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-testing")
    registry = _registry(tmp_path)
    assert _run(skills, registry, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool"] == "devin-learning"
    assert report["command"] == "catalog-bridge"
    assert report["scanned"] == 1
    assert report["registered"] == ["learned-testing"]
    assert report["dry_run"] is False


def test_default_registry_honors_devin_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVIN_CONFIG_DIR", str(tmp_path / "cfg"))
    skills = tmp_path / "skills"
    _write_skill(skills, "learned-x")
    assert cli.main(["catalog-bridge", str(skills)]) == 0
    registry = default_registry_path()
    assert registry.is_file()
    assert registry == (
        tmp_path / "cfg" / ".devin-ecosystem" / "skill-catalog.json"
    )
    assert "skill:learned-x" in _items(registry)


def test_load_registry_missing_file_returns_skeleton(tmp_path):
    data = load_registry(tmp_path / "absent" / "skill-catalog.json")
    assert data == {"version": 1, "items": {}}
