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
