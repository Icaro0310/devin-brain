"""Learning submodule carries its own ``__version__``, surfaced by CLI/report."""

import json
from importlib.metadata import version

import pytest

import devin_memory.learning
from devin_memory.learning import cli


def test_import() -> None:
    assert devin_memory.learning.__version__


def test_version_matches_package_distribution() -> None:
    assert devin_memory.learning.__version__ == version("devin-memory")


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
