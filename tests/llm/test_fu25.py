"""FU-25: fake mode never overwrites the committed reports, and a fake-tokenizer report is stale.

Part 1: in fake mode (``TRIPARTITE_LLM=fake``, as in CI), ``measure-context`` and ``calibrate``
refuse any ``--out`` that resolves to ``reports/context_report.json`` or
``reports/token_calibration.json``, and exit 1 with ``refusing to overwrite <path> in fake mode;
pass --out``. Part 2: in every mode, a report whose tokenizer is ``fake-bytes@v1`` is stale for
``doctor`` (``test_doctor.py``), ``calibrate`` and ``run start`` (``require_valid_calibration``;
the pipeline side is in ``tests/pipeline/test_errors.py``).

The fake reports of part 2 are written under ``tmp_path`` and injected; no test writes at the
committed paths. As a safety net, a fixture compares the committed files' bytes after every test
here and restores them if a regression ever changed them, then fails.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fixtures.model.reports import (
    FAKE_REPO,
    FAKE_REVISION,
    calibration_report,
    write_calibration_report,
    write_context_report,
)
from tripartite.config import REPO_ROOT, StackConfig
from tripartite.llm import cli
from tripartite.llm.calibration import (
    CALIBRATION_REPORT_PATH,
    calibration_status,
    require_valid_calibration,
)
from tripartite.llm.context import CONTEXT_REPORT_PATH, context_report_status, load_context_report
from tripartite.llm.errors import CalibrationMissingError

runner = CliRunner()
COMMITTED = (CONTEXT_REPORT_PATH, CALIBRATION_REPORT_PATH)


@pytest.fixture(autouse=True)
def committed_reports_unchanged() -> Iterator[None]:
    before = {path: path.read_bytes() for path in COMMITTED}
    yield
    changed = [path for path in COMMITTED if path.read_bytes() != before[path]]
    for path in changed:
        path.write_bytes(before[path])
    assert changed == [], f"a test changed a committed report (restored): {changed}"


def refusal(command: str, path: Path) -> str:
    shown = path.relative_to(REPO_ROOT).as_posix()
    return f"model {command}: refusing to overwrite {shown} in fake mode; pass --out\n"


def out_spellings(tmp_path: Path, target: Path) -> dict[str, list[str]]:
    """Every way the test spells ``--out`` for ``target``: the default (context report only), a
    relative path from the repository root, a path through ``..``, and a symlink."""
    link = tmp_path / "link.json"
    link.symlink_to(target)
    via_parent = target.parent / ".." / target.parent.name / target.name
    return {
        "relative": ["--out", os.path.relpath(target, REPO_ROOT)],
        "dotdot": ["--out", str(via_parent)],
        "symlink": ["--out", str(link)],
    }


# --- part 1: fake mode refuses the committed paths ---------------------------------------------


@pytest.mark.parametrize("command", ["measure-context", "calibrate"])
def test_the_default_out_is_refused_in_fake_mode(command: str) -> None:
    default = CONTEXT_REPORT_PATH if command == "measure-context" else CALIBRATION_REPORT_PATH

    result = runner.invoke(cli.app, [command])  # TRIPARTITE_LLM=fake, as in CI

    assert result.exit_code == 1
    assert result.output == refusal(command, default) + f"model {command}: FAILED\n"


@pytest.mark.parametrize("command", ["measure-context", "calibrate"])
@pytest.mark.parametrize("target", COMMITTED, ids=["context", "calibration"])
@pytest.mark.parametrize("spelling", ["relative", "dotdot", "symlink"])
def test_every_spelling_of_a_committed_path_is_refused(
    command: str, target: Path, spelling: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    args = out_spellings(tmp_path, target)[spelling]

    result = runner.invoke(cli.app, [command, *args])

    assert result.exit_code == 1
    assert result.output.startswith(refusal(command, target))


def test_measure_context_still_writes_elsewhere_in_fake_mode(tmp_path: Path) -> None:
    out = tmp_path / "context_report.json"

    result = runner.invoke(cli.app, ["measure-context", "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = load_context_report(out)
    assert report is not None
    assert (report.tokenizer, report.revision) == (FAKE_REPO, FAKE_REVISION)


def test_calibrate_elsewhere_still_needs_the_real_server(tmp_path: Path) -> None:
    """FU-25 moves no other refusal: calibrate in fake mode still exits 1 with ``--out tmp``."""
    result = runner.invoke(cli.app, ["calibrate", "--out", str(tmp_path / "calibration.json")])

    assert result.exit_code == 1
    assert "calibration needs the real server" in result.output
    assert not (tmp_path / "calibration.json").exists()


def test_outside_fake_mode_the_committed_paths_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")

    for path in COMMITTED:  # returns without exiting; nothing is written by this check
        cli._refuse_committed_report_in_fake_mode("measure-context", path)


# --- part 2: a fake-tokenizer report is stale, in every mode -----------------------------------


@pytest.mark.parametrize("mode", ["fake", "ollama"])
def test_a_fake_tokenizer_calibration_is_stale(
    mode: str, stack: StackConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPARTITE_LLM", mode)
    path = write_calibration_report(
        tmp_path / "token_calibration.json",
        calibration_report(stack, tokenizer_repo=FAKE_REPO, tokenizer_revision=FAKE_REVISION),
    )

    status = calibration_status(stack, path)

    assert status.status == "stale"
    assert "fake tokenizer fake-bytes@v1" in status.detail
    with pytest.raises(CalibrationMissingError, match="is stale: written with the fake tokenizer"):
        require_valid_calibration(stack, path)  # what run start calls before its warm-up


@pytest.mark.parametrize("mode", ["fake", "ollama"])
def test_a_fake_tokenizer_context_report_is_stale(
    mode: str, stack: StackConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPARTITE_LLM", mode)
    path = write_context_report(
        tmp_path / "context_report.json", stack, tokenizer=FAKE_REPO, revision=FAKE_REVISION
    )

    status = context_report_status(stack, path)

    assert status.status == "stale"
    assert "fake tokenizer fake-bytes@v1" in status.detail


def test_context_report_status(stack: StackConfig, tmp_path: Path) -> None:
    path = tmp_path / "context_report.json"
    assert context_report_status(stack, path).status == "missing"

    write_context_report(path, stack)
    assert context_report_status(stack, path).status == "valid"

    write_context_report(path, stack, revision="0" * 40)
    stale = context_report_status(stack, path)
    assert stale.status == "stale"
    assert "revision" in stale.detail

    path.write_text("{}", encoding="utf-8")
    assert context_report_status(stack, path).status == "invalid"


def test_the_committed_reports_are_valid_for_the_pinned_stack(stack: StackConfig) -> None:
    """Read-only: what ``make doctor`` must say about M3's reports."""
    assert context_report_status(stack).status == "valid"
    assert calibration_status(stack).status == "valid"


def test_calibrate_refuses_a_fake_context_report_before_loading_anything(
    stack: StackConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_network: list[str],
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("calibrate loaded the tokenizer before checking the report")

    monkeypatch.setattr(cli, "tokenizer_from_env", refuse)
    report = write_context_report(
        tmp_path / "context_report.json", stack, tokenizer=FAKE_REPO, revision=FAKE_REVISION
    )
    out = tmp_path / "calibration.json"

    result = runner.invoke(
        cli.app, ["calibrate", "--context-report", str(report), "--out", str(out)]
    )

    assert result.exit_code == 1
    assert f"{report} is stale: written with the fake tokenizer fake-bytes@v1" in result.output
    assert not out.exists()
    assert no_network == []
