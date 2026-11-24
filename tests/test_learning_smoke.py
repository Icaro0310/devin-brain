"""Learning submodule carries its own ``__version__``, surfaced by CLI/report."""

import json
from pathlib import Path

import pytest

import devin_memory.learning
from devin_memory.learning import cli

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


def _declared_version() -> str:
    """``[project].version`` from pyproject.toml — what the built distribution reports."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)["project"]["version"]
    in_project = False
    for line in text.splitlines():
        if line.startswith("["):
            in_project = line.strip() == "[project]"
        elif in_project and line.strip().startswith("version"):
            return line.split('"')[1]
    raise AssertionError("pyproject.toml [project].version not found")


def test_import() -> None:
    assert devin_memory.learning.__version__


def test_version_matches_package_distribution() -> None:
    assert devin_memory.learning.__version__ == _declared_version()


def test_version_flag_reports_submodule_version(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert devin_memory.learning.__version__ in capsys.readouterr().out


def test_extract_report_uses_submodule_version(
    sessions_db, tmp_path, capsys: pytest.CaptureFixture
) -> None:
    out = tmp_path / "drafts"
    rc = cli.main(
        ["extract", "--sessions-db", str(sessions_db), "--out", str(out), "--json"]
    )
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == devin_memory.learning.__version__
