"""``tripartite run``: start, resume and re-score runs (ARCHITECTURE.md D1, D7, D9).

- ``start --config <path>``: a new run (``make baseline``, ``make baseline-smoke``).
- ``start --resume <run_id>``: resume an interrupted or failed run (``make resume``).
- ``rescore --run <run_id>``: re-score a finished run from its stored plans into
  ``runs/<run_id>/rescore-<UTC ts>/`` and compare every re-written file with the original byte for
  byte; any difference exits 1 (``make eval``, D1 Phase 0 exit item 5).

``start`` prints the run id first, one line per pair, then the six official scores as
percentages (stored files keep rates in [0, 1], D7). It exits 0 when the run succeeded, 1 when
it failed or could not start, and 130 when it was interrupted (Ctrl-C or SIGTERM); an
interrupted or failed run can be resumed. With the real model, a missing or stale token
calibration, including one counted with the fake tokenizer, stops ``start`` before any call
(D4, FU-25).
"""

import signal
from pathlib import Path
from types import FrameType
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from tripartite.config import ConfigError, load_run_config
from tripartite.data.manifest import DataError
from tripartite.evaluation.bridge_client import BridgeError, EvaluationError
from tripartite.llm.errors import LLMError
from tripartite.pipeline.lock import ModelLockHeldError
from tripartite.pipeline.metrics import format_metrics
from tripartite.pipeline.resume import open_resume
from tripartite.pipeline.run import (
    RescoreError,
    ResumeError,
    RunDeps,
    RunSession,
    execute,
    open_run,
    rescore_run,
)
from tripartite.planner.prompt import PromptError
from tripartite.runlog.reader import RunLogError

app = typer.Typer(no_args_is_help=True, add_completion=False)

EXIT_INTERRUPTED = 130
CANNOT_START = (
    ConfigError,
    DataError,
    LLMError,
    ModelLockHeldError,
    OSError,
    PromptError,
    ResumeError,
    RunLogError,
    ValidationError,
    ValueError,
)
"""Errors that stop ``start`` before a run begins (nothing was called)."""


@app.callback()
def main() -> None:
    """Start, resume and re-score runs (ARCHITECTURE.md D1, D7)."""


def default_deps() -> RunDeps:
    """The CLI's run dependencies: the repository's ``runs/``, the lock, the real paths."""
    return RunDeps()


def _fail(command: str, problems: list[str]) -> NoReturn:
    for problem in problems:
        typer.echo(f"run {command}: {problem}", err=True)
    typer.echo(f"run {command}: FAILED", err=True)
    raise typer.Exit(1)


def _interrupt_on_sigterm() -> None:
    """End on SIGTERM as on Ctrl-C, so the run is marked ``interrupted`` and can be resumed."""

    def handler(_signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


@app.command()
def start(
    config: Annotated[
        Path | None, typer.Option("--config", help="The run config (configs/*.yaml).")
    ] = None,
    resume: Annotated[
        str | None, typer.Option("--resume", help="The id of a run to resume.")
    ] = None,
) -> None:
    """Start a run from a config, or resume one by its run id."""
    if (config is None) == (resume is None):
        _fail("start", ["pass exactly one of --config <path> or --resume <run_id>"])
    deps = default_deps()
    deps.echo = typer.echo  # one progress line per pair
    try:
        session: RunSession = (
            open_run(load_run_config(config), deps)
            if config is not None
            else open_resume(str(resume), deps)
        )
    except CANNOT_START as exc:
        _fail("start", [f"{type(exc).__name__}: {exc}"])
    action = "resuming" if resume is not None else "started"
    typer.echo(f"run start: {action} {session.run_id} in {session.run_dir}")
    _interrupt_on_sigterm()
    outcome = execute(session)
    if outcome.status == "succeeded" and outcome.metrics is not None:
        for line in format_metrics(outcome.metrics):
            typer.echo(f"run start: {line}")
        typer.echo(f"run start: succeeded: {outcome.run_dir}")
        return
    error = outcome.error
    detail = f"{error.type}: {error.message}" if error is not None else "no detail"
    typer.echo(f"run start: {outcome.status}: {detail}", err=True)
    typer.echo(f"run start: resume with `make resume RUN={outcome.run_id}`", err=True)
    raise typer.Exit(EXIT_INTERRUPTED if outcome.status == "interrupted" else 1)


@app.command()
def rescore(
    run: Annotated[str, typer.Option("--run", help="The id of a succeeded run.")],
) -> None:
    """Re-score a finished run from its stored plans and compare every re-written file with the
    original byte for byte (R1). Exits 1 on any difference."""
    deps = default_deps()
    try:
        report = rescore_run(run, runs_dir=deps.runs_dir, bridge=deps.bridge, clock=deps.clock)
    except (
        BridgeError,
        DataError,
        EvaluationError,
        OSError,
        RescoreError,
        RunLogError,
        ValidationError,
        ValueError,
    ) as exc:
        _fail("rescore", [f"{type(exc).__name__}: {exc}"])
    mismatched = {line.split(":", 1)[0] for line in report.mismatches}
    for name in report.compared:
        if name not in mismatched:
            typer.echo(f"run rescore: OK {name}")
    for line in report.mismatches:
        typer.echo(f"run rescore: MISMATCH {line}")
    typer.echo(f"run rescore: wrote {report.out_dir}")
    if not report.ok:
        _fail("rescore", [f"{len(report.mismatches)} file(s) differ from the run (R1)"])
    typer.echo(f"run rescore: {len(report.compared)} files byte-identical")
