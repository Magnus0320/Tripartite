"""``tripartite log``: run-log tools (ARCHITECTURE.md D7 §MLflow, D9).

- ``mlflow-sync --run <run_id>``: copy one finished batch run from ``runs/<run_id>/`` into the
  local MLflow file store ``./mlruns`` (``make mlflow-sync RUN=<run_id>``; browse it with
  ``make mlflow-ui``). Manual only: no run syncs itself. Syncing the same run again replaces its
  MLflow run. A ``kind=single`` run is skipped with exit 0. Anything missing, such as
  ``metrics.json`` for a run that did not finish, exits 1 and writes nothing.
"""

from typing import Annotated

import typer

from tripartite.runlog.mlflow_sync import EXPERIMENT, MlflowSyncError, sync_run

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Run-log tools (ARCHITECTURE.md D7)."""


@app.command("mlflow-sync")
def mlflow_sync(
    run: Annotated[str, typer.Option("--run", help="The id of the batch run to sync.")],
) -> None:
    """Sync one finished batch run to the local MLflow store."""
    try:
        result = sync_run(run)
    except MlflowSyncError as exc:
        typer.echo(f"log mlflow-sync: {exc}", err=True)
        typer.echo("log mlflow-sync: FAILED", err=True)
        raise typer.Exit(1) from None
    if result.skipped:
        typer.echo(f"skipped: run {result.run_id} is kind=single")
        return
    typer.echo(
        f"log mlflow-sync: synced run {result.run_id} to {result.store} "
        f"(experiment {EXPERIMENT}, MLflow run {result.mlflow_run_id})"
    )
