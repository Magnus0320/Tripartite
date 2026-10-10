"""Manual MLflow sync of one finished batch run (ARCHITECTURE.md D7 §MLflow, M6).

MLflow is a derived, disposable index for comparing runs in a UI. The run directory is the
record: if the two disagree, the run directory wins, and nothing in the pipeline or the API
reads MLflow. Syncing is manual only: ``tripartite log mlflow-sync --run <run_id>``
(``make mlflow-sync RUN=<run_id>``).

``sync_run`` reads and validates everything it needs before it touches MLflow, so a problem
(a missing ``metrics.json``, say) is an error and never a partial sync, and a failed sync
leaves an earlier sync of the same run alone. It then deletes any active MLflow run tagged with
this ``tripartite.run_id`` and creates a new one, so repeated syncs converge on one run. The
delete is MLflow's own soft delete; ``mlflow gc`` purges such runs.

The store is a local file store (``./mlruns``). MLflow 3 refuses one unless
``MLFLOW_ALLOW_FILE_STORE=true``, so that variable is set for the duration of the sync only,
together with ``MLFLOW_DISABLE_TELEMETRY=true``: a sync makes no network call.

``tripartite.architecture_version`` is line 1 of ``ARCHITECTURE.md`` as committed at the run's
own ``git_commit`` (``git show <commit>:ARCHITECTURE.md``): the version the run was built under.
"""

import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.schema import (
    LlmCallEvent,
    Metrics,
    MetricsSeed,
    OfficialMetric,
    RunManifest,
    validate_run_id,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
RUNS_DIR: Final = REPO_ROOT / "runs"
MLRUNS_DIR: Final = REPO_ROOT / "mlruns"
EXPERIMENT: Final = "tripartite"
RUN_ID_TAG: Final = "tripartite.run_id"

MANIFEST_FILE: Final = "manifest.json"
METRICS_FILE: Final = "metrics.json"
EVENTS_FILE: Final = "events.jsonl"
ARCHITECTURE_FILE: Final = "ARCHITECTURE.md"

METRIC_KEYS: Final[dict[OfficialMetric, str]] = {
    "Delivery Rate": "delivery_rate",
    "Commonsense Constraint Micro Pass Rate": "commonsense_micro",
    "Commonsense Constraint Macro Pass Rate": "commonsense_macro",
    "Hard Constraint Micro Pass Rate": "hard_micro",
    "Hard Constraint Macro Pass Rate": "hard_macro",
    "Final Pass Rate": "final_pass_rate",
}
"""Official metric name -> MLflow metric key (D7 §MLflow)."""
GENERATION_PARAMS: Final = ("num_predict", "temperature", "top_p", "top_k", "min_p")
"""Params read from ``run_start.config.generation``."""

MLFLOW_ENV: Final = {
    "MLFLOW_ALLOW_FILE_STORE": "true",
    "MLFLOW_DISABLE_TELEMETRY": "true",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
}

_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ARCHITECTURE_LINE = re.compile(
    r"^ARCHITECTURE\.md · (v[0-9]+\.[0-9]+) · [0-9]{4}-[0-9]{2}-[0-9]{2}$"
)
_GIT_TIMEOUT_S: Final = 30


class MlflowSyncError(Exception):
    """A run cannot be synced. Nothing was written to MLflow."""


@dataclass(frozen=True)
class SyncResult:
    run_id: str
    skipped: bool
    """True for a ``kind=single`` run: only batch runs are synced."""
    mlflow_run_id: str | None
    store: Path


@dataclass(frozen=True)
class _Loaded:
    """Everything a sync logs, read and validated before MLflow is touched."""

    tags: dict[str, str]
    params: dict[str, str]
    metrics: list[tuple[str, float, int]]
    """``(key, value, step)``."""
    artifacts: list[Path]
    start: datetime
    end: datetime


def sync_run(
    run_id: str,
    *,
    runs_dir: Path = RUNS_DIR,
    mlruns_dir: Path = MLRUNS_DIR,
    repo_root: Path = REPO_ROOT,
) -> SyncResult:
    """Sync ``runs_dir/<run_id>`` to the MLflow file store at ``mlruns_dir``.

    ``repo_root`` is the git checkout whose history holds the run's commit. Raises
    ``MlflowSyncError`` for anything missing or invalid.
    """
    try:
        run_dir = runs_dir / validate_run_id(run_id)
    except ValidationError as exc:
        raise MlflowSyncError(f"{run_id!r} is not a run id") from exc
    if not run_dir.is_dir():
        raise MlflowSyncError(f"no run {run_id} in {runs_dir}")
    manifest = _load(run_dir / MANIFEST_FILE, RunManifest)
    if manifest.run_start.kind == "single":
        return SyncResult(run_id=run_id, skipped=True, mlflow_run_id=None, store=mlruns_dir)
    loaded = _load_run(run_id, run_dir, manifest, repo_root)
    with _mlflow_env():
        mlflow_run_id = _write(run_id, loaded, mlruns_dir)
    return SyncResult(run_id=run_id, skipped=False, mlflow_run_id=mlflow_run_id, store=mlruns_dir)


def architecture_version(git_commit: str, repo_root: Path = REPO_ROOT) -> str:
    """``v<major>.<minor>`` from line 1 of ``ARCHITECTURE.md`` as committed at ``git_commit``."""
    if not _GIT_COMMIT.fullmatch(git_commit):
        raise MlflowSyncError(
            f"cannot read {ARCHITECTURE_FILE} at commit {git_commit!r}: not a full commit id"
        )
    try:
        shown = subprocess.run(
            ["git", "show", f"{git_commit}:{ARCHITECTURE_FILE}"],
            cwd=repo_root,
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MlflowSyncError(
            f"cannot read {ARCHITECTURE_FILE} at commit {git_commit}: {exc}"
        ) from exc
    if shown.returncode != 0:
        detail = shown.stderr.decode(errors="replace").strip().splitlines()
        raise MlflowSyncError(
            f"cannot read {ARCHITECTURE_FILE} at commit {git_commit} in {repo_root}: "
            f"{detail[-1] if detail else 'git show failed'}"
        )
    first_line = shown.stdout.split(b"\n", 1)[0].decode(errors="replace").rstrip("\r")
    match = _ARCHITECTURE_LINE.fullmatch(first_line)
    if match is None:
        raise MlflowSyncError(
            f"line 1 of {ARCHITECTURE_FILE} at commit {git_commit} is not "
            f"'{ARCHITECTURE_FILE} · v<major>.<minor> · <date>': {first_line!r}"
        )
    return match.group(1)


# --- reading the run directory -----------------------------------------------------------------


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise MlflowSyncError(f"{path.name} is missing in {path.parent}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise MlflowSyncError(f"cannot read {path}: {exc}") from exc
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        raise MlflowSyncError(f"{path} is not a valid {model.__name__}: {exc}") from exc


def _load_run(run_id: str, run_dir: Path, manifest: RunManifest, repo_root: Path) -> _Loaded:
    metrics = _load(run_dir / METRICS_FILE, Metrics)
    if metrics.run_id != run_id:
        raise MlflowSyncError(f"{METRICS_FILE} belongs to run {metrics.run_id}, not {run_id}")
    seed_files = [run_dir / f"metrics_seed{seed}.json" for seed in metrics.seeds]
    for path in seed_files:
        _load(path, MetricsSeed)
    start = manifest.run_start
    generation = _generation(start.config)

    tags = {
        RUN_ID_TAG: run_id,
        "tripartite.kind": start.kind,
        "tripartite.config_hash": start.config_hash,
        "tripartite.prompt_version": start.prompt_version,
        "tripartite.parser_version": start.parser_version,
        "tripartite.model_tag": start.model.tag,
        "tripartite.model_digest": start.model.digest,
        "tripartite.evaluator_commit": start.evaluator.upstream_commit,
        "tripartite.dataset_revision": start.dataset.revision,
        "tripartite.git_commit": start.env.git_commit,
        "tripartite.architecture_version": architecture_version(start.env.git_commit, repo_root),
    }
    params = {
        "config_hash": start.config_hash,
        "model_tag": start.model.tag,
        "model_digest": start.model.digest,
        "quant": start.model.quant,
        "num_ctx": json.dumps(_num_ctx(run_dir / EVENTS_FILE)),
        **{name: json.dumps(generation[name]) for name in GENERATION_PARAMS},
        "seed_list": json.dumps(metrics.seeds),
        "prompt_version": start.prompt_version,
        "parser_version": start.parser_version,
        "evaluator_commit": start.evaluator.upstream_commit,
        "dataset_revision": start.dataset.revision,
        "n_queries": json.dumps(metrics.n_queries),
        "subset": json.dumps(metrics.subset),
    }
    return _Loaded(
        tags=tags,
        params=params,
        metrics=_metric_points(metrics),
        artifacts=[run_dir / MANIFEST_FILE, run_dir / METRICS_FILE, *seed_files],
        start=metrics.created_at,
        end=metrics.finished_at,
    )


def _generation(config: dict[str, Any]) -> dict[str, Any]:
    generation = config.get("generation")
    if not isinstance(generation, dict):
        raise MlflowSyncError("run_start.config has no generation block")
    if missing := [name for name in GENERATION_PARAMS if name not in generation]:
        raise MlflowSyncError(f"run_start.config.generation lacks {missing}")
    return generation


def _num_ctx(events: Path) -> int:
    """The one ``num_ctx`` the run sent; ``run_start`` does not carry it (D9 §M5a, AQ4)."""
    try:
        sent = {e.request.num_ctx for e in read_events(events) if isinstance(e, LlmCallEvent)}
    except FileNotFoundError:
        raise MlflowSyncError(f"{events.name} is missing in {events.parent}") from None
    except (OSError, RunLogError) as exc:
        raise MlflowSyncError(f"cannot read {events}: {exc}") from exc
    if len(sent) != 1:
        raise MlflowSyncError(
            f"{events.name} must hold llm_call events with one num_ctx, found {sorted(sent)}"
        )
    return sent.pop()


def _metric_points(metrics: Metrics) -> list[tuple[str, float, int]]:
    """Every metric to log. MLflow cannot store null, so a null value is skipped."""
    points: list[tuple[str, float, int]] = []
    for official, key in METRIC_KEYS.items():
        summary = metrics.metrics[official]
        points += [(key, value, int(seed)) for seed, value in summary.per_seed.items()]
        points.append((f"{key}_mean", summary.mean, 0))
        if summary.sd is not None:
            points.append((f"{key}_sd", summary.sd, 0))
    optional = {
        "tokens_input_mean": metrics.tokens.input.mean,
        "tokens_output_mean": metrics.tokens.output.mean,
        "latency_wall_ms_median": metrics.latency_ms.wall.median,
        "parse_failure_rate": metrics.parse.failure_rate,
    }
    points += [(key, value, 0) for key, value in optional.items() if value is not None]
    return points


# --- writing to MLflow -------------------------------------------------------------------------


@contextmanager
def _mlflow_env() -> Iterator[None]:
    """Set ``MLFLOW_ENV`` for the block, then restore what was there."""
    before = {name: os.environ.get(name) for name in MLFLOW_ENV}
    os.environ.update(MLFLOW_ENV)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _write(run_id: str, loaded: _Loaded, mlruns_dir: Path) -> str:
    # Imported here: MLflow takes seconds to import, and only a real sync needs it.
    from mlflow.entities import Metric, Param, ViewType
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    try:
        client = MlflowClient(tracking_uri=str(mlruns_dir.resolve()))
        experiment = client.get_experiment_by_name(EXPERIMENT)
        experiment_id = (
            experiment.experiment_id
            if experiment is not None
            else client.create_experiment(EXPERIMENT)
        )
        for old in client.search_runs(
            [experiment_id],
            filter_string=f"tags.`{RUN_ID_TAG}` = '{run_id}'",
            run_view_type=ViewType.ACTIVE_ONLY,
        ):
            client.delete_run(old.info.run_id)
        run = client.create_run(
            experiment_id, start_time=_millis(loaded.start), tags=loaded.tags, run_name=run_id
        )
        mlflow_run_id: str = run.info.run_id
        end = _millis(loaded.end)
        client.log_batch(
            mlflow_run_id,
            metrics=[Metric(key, value, end, step) for key, value, step in loaded.metrics],
            params=[Param(key, value) for key, value in loaded.params.items()],
        )
        for path in loaded.artifacts:
            client.log_artifact(mlflow_run_id, str(path))
        client.set_terminated(mlflow_run_id, status="FINISHED", end_time=end)
    except MlflowException as exc:
        raise MlflowSyncError(f"MLflow refused the sync to {mlruns_dir}: {exc}") from exc
    return mlflow_run_id
