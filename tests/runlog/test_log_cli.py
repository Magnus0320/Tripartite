"""``tripartite log mlflow-sync`` (D7 §MLflow): output and exit codes."""

from functools import partial

import pytest
from typer.testing import CliRunner

from tests.runlog import samples
from tests.runlog.conftest import Workspace
from tripartite.cli import app as root_app
from tripartite.runlog import cli
from tripartite.runlog.mlflow_sync import sync_run

runner = CliRunner()


@pytest.fixture
def cli_workspace(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    """The command syncs from and to ``tmp_path`` instead of the repository's directories."""
    in_tmp_path = partial(
        sync_run,
        runs_dir=workspace.runs_dir,
        mlruns_dir=workspace.mlruns_dir,
        repo_root=workspace.repo,
    )
    monkeypatch.setattr(cli, "sync_run", in_tmp_path)
    return workspace


def test_a_batch_run_is_synced(cli_workspace: Workspace) -> None:
    cli_workspace.write_run()

    result = runner.invoke(cli.app, ["mlflow-sync", "--run", samples.RUN_ID])

    assert result.exit_code == 0, result.output
    assert f"log mlflow-sync: synced run {samples.RUN_ID} to" in result.output
    assert "experiment tripartite" in result.output
    assert (cli_workspace.mlruns_dir / "0").is_dir()


def test_a_single_run_exits_0_with_the_skip_line(cli_workspace: Workspace) -> None:
    cli_workspace.write_run(run_id=samples.OTHER_RUN_ID)

    result = runner.invoke(cli.app, ["mlflow-sync", "--run", samples.OTHER_RUN_ID])

    assert result.exit_code == 0
    assert result.output == f"skipped: run {samples.OTHER_RUN_ID} is kind=single\n"
    assert not cli_workspace.mlruns_dir.exists()


def test_a_missing_metrics_file_exits_1(cli_workspace: Workspace) -> None:
    run_dir = cli_workspace.write_run()
    (run_dir / "metrics.json").unlink()

    result = runner.invoke(cli.app, ["mlflow-sync", "--run", samples.RUN_ID])

    assert result.exit_code == 1
    assert "log mlflow-sync: metrics.json is missing" in result.output
    assert "log mlflow-sync: FAILED" in result.output
    assert not cli_workspace.mlruns_dir.exists()


def test_run_is_required() -> None:
    result = runner.invoke(cli.app, ["mlflow-sync"])

    assert result.exit_code == 2


def test_the_root_command_reaches_it(cli_workspace: Workspace) -> None:
    cli_workspace.write_run(run_id=samples.OTHER_RUN_ID)

    result = runner.invoke(root_app, ["log", "mlflow-sync", "--run", samples.OTHER_RUN_ID])

    assert result.exit_code == 0
    assert result.output == f"skipped: run {samples.OTHER_RUN_ID} is kind=single\n"
