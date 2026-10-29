"""MM-4 tests: ``devin-memory prime`` — hook-ready, filtered, bounded."""

from __future__ import annotations

import pytest

from devin_memory import ops
from devin_memory.cli import main
from devin_memory.store import MemoryStore

from fixtures import CLEAN_FACT, CLEAN_FACT_2, SECRET_FACT


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def test_prime_prints_header_and_active_entries(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, CLEAN_FACT_2)
    text = ops.prime(store)
    assert text.startswith(ops.PRIME_HEADER)
    assert f"- {CLEAN_FACT}" in text
    assert f"- {CLEAN_FACT_2}" in text


def test_prime_excludes_quarantined_proposed_retracted(store):
    ops.retain(store, CLEAN_FACT)
    ops.retain(store, SECRET_FACT)  # quarantined
    store.insert("proposed idea", status="proposed")
    dead = ops.retain(store, "retracted idea")
    ops.retract(store, dead.id)

    text = ops.prime(store)
    assert CLEAN_FACT in text
    assert "proposed idea" not in text
    assert "retracted idea" not in text
    assert SECRET_FACT not in text  # secret values never printed


def test_prime_workspace_scoping(store):
    ops.retain(store, "global fact")
    ops.retain(store, "project fact", workspace="/ws/alpha")

    all_text = ops.prime(store)
    assert "project fact" in all_text  # no filter -> everything

    alpha = ops.prime(store, workspace="/ws/alpha")
    assert "global fact" in alpha
    assert "project fact" in alpha

    beta = ops.prime(store, workspace="/ws/beta")
    assert "global fact" in beta
    assert "project fact" not in beta


def test_prime_profile_gating(store):
    ops.retain(store, "unprofiled fact", profile="corporate")
    ops.retain(store, "personal fact", profile="personal")

    corp = ops.prime(store, profile="corporate")
    assert "unprofiled fact" in corp
    assert "personal fact" not in corp

    pers = ops.prime(store, profile="personal")
    assert "personal fact" in pers
    assert "unprofiled fact" not in pers


def test_prime_profile_defaults_to_identity(store, tmp_path, monkeypatch):
    """Corporate default: unknown env + no profile file -> corporate."""
    monkeypatch.delenv("DEVIN_ECOSYSTEM_PROFILE", raising=False)
    monkeypatch.setenv("DEVIN_CONFIG_DIR", str(tmp_path / "no-config"))
    ops.retain(store, "corp fact", profile="corporate")
    ops.retain(store, "personal fact", profile="personal")
    text = ops.prime(store)  # profile resolved via identity -> corporate
    assert "corp fact" in text
    assert "personal fact" not in text


def test_prime_max_tokens_bounds_output(store):
    long_fact = "y" * 400
    ops.retain(store, long_fact)
    ops.retain(store, "tiny")
    text = ops.prime(store, max_tokens=30)  # ~120 chars of budget
    assert text.startswith(ops.PRIME_HEADER)
    assert "tiny" in text  # small entries still pack in
    assert long_fact not in text


def test_prime_empty_store(store):
    text = ops.prime(store)
    assert text.startswith(ops.PRIME_HEADER)
    assert "(no active memories)" in text


def test_cli_prime_end_to_end(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    main(["--db", db, "retain", CLEAN_FACT])
    main(["--db", db, "retain", SECRET_FACT])
    capsys.readouterr()
    assert main(["--db", db, "prime"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# devin-memory: recalled context")
    assert CLEAN_FACT in out
    assert SECRET_FACT not in out

    assert (
        main(["--db", db, "prime", "--workspace", "/nowhere",
              "--max-tokens", "16"])
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("# devin-memory: recalled context")


# ---------------------------------------------------------------------------
# prime --state-md: generated ecosystem state injection (fail-open)
# ---------------------------------------------------------------------------

STATE_MD = """# Ecosystem state report

_Generated 2026-10-28T12:00:00Z by devin-powerups_

## Drift

| repo | status | notes |
| --- | --- | --- |
| devin-brain | clean | - |
| devin-state | ahead 2 | push pending |

## Service health

- devin-memory-mcp: ok
- obsidian-mcp: down (connection refused)

## Open PRs

- Icaro0310/devin-brain#65 - feat: prime state block
- Icaro0310/devin-state#71 - fix: reap stale locks
"""


def _write_state(tmp_path, text: str = STATE_MD):
    state_file = tmp_path / "current-state.md"
    state_file.write_text(text, encoding="utf-8")
    return state_file


def test_prime_state_happy_path(tmp_path):
    state_file = _write_state(tmp_path)
    text = ops.prime_state(state_md=state_file)
    assert text.startswith("## ecosystem state")
    assert "2026-10-28T12:00:00Z" in text  # generated timestamp
    assert "| devin-brain | clean |" in text  # drift row
    assert "obsidian-mcp: down" in text  # service health line
    assert "devin-state#71" in text  # open PR
    assert "…(truncated)" not in text


def test_prime_state_missing_file_is_unavailable(tmp_path):
    text = ops.prime_state(state_md=tmp_path / "nope.md")
    assert text.startswith("state: unavailable")
    assert "not found" in text


def test_prime_state_unreadable_file_is_unavailable(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00\x01 not utf-8")
    text = ops.prime_state(state_md=bad)
    assert text.startswith("state: unavailable")


def test_prime_state_env_var_search(tmp_path, monkeypatch):
    state_file = _write_state(tmp_path)
    monkeypatch.setenv("DEVIN_ECOSYSTEM_STATE", str(state_file))
    text = ops.prime_state()  # no --state-md: env var is probed first
    assert "ecosystem state" in text
    assert "| devin-brain | clean |" in text


def test_prime_state_nothing_found_is_unavailable(tmp_path, monkeypatch):
    """No flag, no env, no default file -> one-line notice, never an error."""
    monkeypatch.delenv("DEVIN_ECOSYSTEM_STATE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # ~/devin/... resolves empty
    monkeypatch.chdir(tmp_path)  # ./reports/... resolves empty
    text = ops.prime_state()
    assert text == "state: unavailable (no state file in search path)\n"


def test_prime_state_max_chars_truncates(tmp_path):
    rows = "\n".join(
        f"- Icaro0310/repo-{i:03d}#{i} - pull request number {i}"
        for i in range(60)
    )
    state_file = _write_state(
        tmp_path, f"generated 2026-10-28\n\n## Open PRs\n\n{rows}\n"
    )
    text = ops.prime_state(state_md=state_file, max_chars=400)
    assert len(text) <= 400
    assert text.rstrip().endswith("…(truncated)")
    assert "repo-059" not in text  # tail rows dropped


def test_cli_prime_appends_state_block(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    state_file = _write_state(tmp_path)
    main(["--db", db, "retain", CLEAN_FACT])
    capsys.readouterr()
    assert (
        main(["--db", db, "prime", "--state-md", str(state_file)])
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("# devin-memory: recalled context")
    assert CLEAN_FACT in out
    assert "## ecosystem state" in out
    assert "devin-state#71" in out


def test_cli_prime_state_missing_still_exits_0(tmp_path, capsys):
    db = str(tmp_path / "memory.db")
    assert (
        main(
            ["--db", db, "prime",
             "--state-md", str(tmp_path / "absent.md")]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("# devin-memory: recalled context")
    assert "state: unavailable" in out
