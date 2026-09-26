"""``tripartite data fetch`` and ``tripartite data verify`` (ARCHITECTURE.md D9 ``make data``)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.data import synthetic
from tripartite import cli as root_cli
from tripartite.data import download, manifest
from tripartite.data.cli import app

runner = CliRunner()


@pytest.fixture
def hub(synthetic_raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake hf_hub_download that leaves the synthetic files where they are."""

    def fake(**kwargs: Any) -> str:
        return str(Path(kwargs["local_dir"]) / kwargs["filename"])

    monkeypatch.setattr(download, "hf_hub_download", fake)


@pytest.mark.usefixtures("hub", "synthetic_zip_pin")
def test_fetch_then_verify_succeeds(data_dir: Path) -> None:
    fetched = runner.invoke(app, ["fetch"])
    assert fetched.exit_code == 0, fetched.output
    assert f"dataset files recorded in {data_dir / 'MANIFEST.json'}" in fetched.output
    assert "sandbox_database.zip: OK" in fetched.output

    again = runner.invoke(app, ["fetch"])
    assert again.exit_code == 0, again.output
    assert "dataset files match" in again.output

    verified = runner.invoke(app, ["verify"])
    assert verified.exit_code == 0, verified.output
    lines = verified.output.splitlines()
    assert lines[-1] == "data verify: OK"
    assert sum(": OK (" in line for line in lines) == 4


@pytest.mark.usefixtures("hub")
def test_fetch_fails_without_the_zip() -> None:
    result = runner.invoke(app, ["fetch"])

    assert result.exit_code == 1
    assert "sandbox_database.zip: missing: download it by hand" in result.output
    assert result.output.splitlines()[-1] == "data fetch: FAILED"


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_fails_and_lists_every_problem(synthetic_raw: Path) -> None:
    manifest.write_manifest(synthetic.matching_manifest(synthetic_raw), manifest.manifest_path())
    (synthetic_raw / "validation.csv").write_bytes(b"truncated")
    (synthetic_raw / "validation_ref_info.jsonl").unlink()

    result = runner.invoke(app, ["verify"])

    assert result.exit_code == 1
    assert "validation.csv: expected" in result.output
    assert "validation_ref_info.jsonl: missing" in result.output
    assert result.output.splitlines()[-1] == "data verify: FAILED"


@pytest.mark.usefixtures("hub", "synthetic_zip_pin")
def test_the_root_cli_reaches_the_data_commands() -> None:
    assert runner.invoke(root_cli.app, ["data", "fetch"]).exit_code == 0
    result = runner.invoke(root_cli.app, ["data", "verify"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "data verify: OK"
