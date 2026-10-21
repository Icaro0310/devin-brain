"""Static assertions for .github/workflows/release-memory.yml.

The release fan-out has no unit-testable code, so these tests pin the
gates that keep a mistagged or manually dispatched run from publishing:
tag-push-only release/fanout, validate before either publish leg, and
the reusable-workflow wiring. A regression here is a supply-chain
release bug, not a style nit — keep the assertions exact.
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-memory.yml"
TAG_PUSH_ONLY = "github.event_name == 'push' && github.ref_type == 'tag'"


def _load() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 parses the literal key `on` as boolean True.
    wf["on"] = wf.pop(True)
    return wf


def test_trigger_is_memory_tag_push():
    wf = _load()
    assert wf["on"]["push"]["tags"] == ["memory-v*"]
    assert "workflow_dispatch" in wf["on"]


def test_release_job_tag_push_only():
    wf = _load()
    release = wf["jobs"]["release"]
    assert release["needs"] == "validate"
    assert release["if"] == TAG_PUSH_ONLY


def test_fanout_requires_validate_and_release():
    wf = _load()
    fanout = wf["jobs"]["fanout"]
    assert sorted(fanout["needs"]) == ["release", "validate"]
    assert fanout["if"] == TAG_PUSH_ONLY


def test_fanout_uses_reusable_release_and_scoped_secrets():
    wf = _load()
    fanout = wf["jobs"]["fanout"]
    assert fanout["uses"] == "Icaro0310/devin-powerups/.github/workflows/release.yml@v1"
    # Explicit secret mapping only — `inherit` would leak unrelated secrets.
    assert set(fanout["secrets"]) == {"OVSX_PAT"}
    assert fanout["with"]["package-dir"] == "adapters/vscode"
    assert fanout["with"]["vscode-ext-dir"] == "adapters/vscode"


def test_validate_gates_tag_manifest_match():
    wf = _load()
    steps = wf["jobs"]["validate"]["steps"]
    tag_steps = [s for s in steps if s.get("if") == "github.ref_type == 'tag'"]
    assert len(tag_steps) == 1
    assert "package.json" in tag_steps[0]["run"]


def test_pypi_dispatch_only_when_wheel_pending_and_nonblocking():
    """The dispatch is the only PyPI trigger (GITHUB_TOKEN emits no
    release.published), so it must run when the wheel is unpublished —
    but a PyPI-side outage must not take the extension fanout down:
    the lookup distinguishes a true 404 from other failures, and the
    dispatch is continue-on-error."""
    steps = _load()["jobs"]["release"]["steps"]
    probe = [s for s in steps if s.get("id") == "wheel"]
    assert len(probe) == 1
    assert "pypi.org/pypi/devin-memory/" in probe[0]["run"]
    # A non-200/404 lookup result must map to a non-dispatch state so a
    # PyPI outage does not trigger a redundant (and failing) dispatch.
    assert "published=unknown" in probe[0]["run"]
    dispatch = [s for s in steps if "gh workflow run" in s.get("run", "")]
    assert len(dispatch) == 1
    assert dispatch[0]["if"] == "steps.wheel.outputs.published == 'false'"
    assert dispatch[0]["continue-on-error"] is True
