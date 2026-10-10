"""``sync_run``: one finished batch run into a local MLflow file store (D7 §MLflow, M6).

Every run directory, MLflow store and git repository here lives in ``tmp_path``.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from mlflow.entities import Run, ViewType
from mlflow.tracking import MlflowClient

from tests.runlog import samples
from tests.runlog.conftest import Workspace
from tripartite.runlog.mlflow_sync import (
    EXPERIMENT,
    MLFLOW_ENV,
    MlflowSyncError,
    architecture_version,
)
from tripartite.runlog.schema import MetricSummary, ParseSummary, Stats, TokenStats

SECOND_RUN_ID = "20260924T080000Z-batch-abababab-9f9f"
OFFICIAL_KEYS = (
    "delivery_rate",
    "commonsense_micro",
    "commonsense_macro",
    "hard_micro",
    "hard_macro",
    "final_pass_rate",
)
T0_MS = int(samples.T0.timestamp() * 1000)

EXPECTED_TAGS = {
    "tripartite.run_id": samples.RUN_ID,
    "tripartite.kind": "batch",
    "tripartite.config_hash": samples.SHA,
    "tripartite.prompt_version": "sp-direct-v1",
    "tripartite.parser_version": "rule-text/v1",
    "tripartite.model_tag": "qwen3:8b-q4_K_M",
    "tripartite.model_digest": "500a1f067a9f" + "0" * 52,
    "tripartite.evaluator_commit": "e52c87f4ac348a3410c46dc3553c519db5ec5e23",
    "tripartite.dataset_revision": "8736504ecfc31b7f8b7e40122873c337e83fff7c",
    "tripartite.architecture_version": "v0.12",
}
"""Plus ``tripartite.git_commit``, which is the throwaway repository's commit."""

EXPECTED_PARAMS = {
    "config_hash": samples.SHA,
    "model_tag": "qwen3:8b-q4_K_M",
    "model_digest": "500a1f067a9f" + "0" * 52,
    "quant": "Q4_K_M",
    "num_ctx": "32768",
    "num_predict": "4096",
    "temperature": "0.7",
    "top_p": "0.8",
    "top_k": "20",
    "min_p": "0.0",
    "seed_list": "[0, 1, 2]",
    "prompt_version": "sp-direct-v1",
    "parser_version": "rule-text/v1",
    "evaluator_commit": "e52c87f4ac348a3410c46dc3553c519db5ec5e23",
    "dataset_revision": "8736504ecfc31b7f8b7e40122873c337e83fff7c",
    "n_queries": "9",
    "subset": "true",
}


@contextmanager
def store(mlruns_dir: Path) -> Iterator[tuple[MlflowClient, str]]:
    """A client on the file store and the ``tripartite`` experiment's id, for reading back."""
    with pytest.MonkeyPatch.context() as patch:
        for name, value in MLFLOW_ENV.items():
            patch.setenv(name, value)
        client = MlflowClient(tracking_uri=str(mlruns_dir))
        experiment = client.get_experiment_by_name(EXPERIMENT)
        assert experiment is not None
        yield client, experiment.experiment_id


def runs(mlruns_dir: Path, view: int = ViewType.ACTIVE_ONLY) -> list[Run]:
    with store(mlruns_dir) as (client, experiment_id):
        return list(client.search_runs([experiment_id], run_view_type=view))


def only_run(mlruns_dir: Path) -> Run:
    (run,) = runs(mlruns_dir)
    return run


def history(mlruns_dir: Path, run: Run, key: str) -> list[tuple[int, float]]:
    with store(mlruns_dir) as (client, _):
        return sorted((m.step, m.value) for m in client.get_metric_history(run.info.run_id, key))


def artifact_names(mlruns_dir: Path, run: Run) -> list[str]:
    with store(mlruns_dir) as (client, _):
        return sorted(a.path for a in client.list_artifacts(run.info.run_id))


def one_seed_no_parses() -> dict[str, Any]:
    """Metrics overrides for a one-seed run where nothing reached the parser: every nullable
    value that MLflow would log is null."""
    empty = Stats(mean=None, median=None, p95=None)
    full = Stats(mean=1.0, median=1.0, p95=1.0)
    base = samples.metrics()
    return {
        "seeds": [0],
        "metrics": {
            key: MetricSummary(per_seed={"0": 0.5}, mean=0.5, sd=None) for key in base.metrics
        },
        "parse": ParseSummary(attempted=0, ok=0, failure_rate=None),
        "tokens": TokenStats(input=empty, output=empty, thinking=empty),
        "latency_ms": base.latency_ms.model_copy(update={"wall": empty, "prefill": full}),
    }


# --- what a sync writes ------------------------------------------------------------------------


def test_the_run_is_named_after_the_run_id_in_the_tripartite_experiment(
    workspace: Workspace,
) -> None:
    workspace.write_run()

    result = workspace.sync()

    run = only_run(workspace.mlruns_dir)
    assert (result.skipped, result.mlflow_run_id) == (False, run.info.run_id)
    assert run.info.run_name == samples.RUN_ID
    assert run.info.status == "FINISHED"
    assert (run.info.start_time, run.info.end_time) == (T0_MS, T0_MS)


def test_every_tag(workspace: Workspace) -> None:
    workspace.write_run()
    workspace.sync()

    tags = only_run(workspace.mlruns_dir).data.tags
    ours = {key: value for key, value in tags.items() if key.startswith("tripartite.")}
    assert ours == EXPECTED_TAGS | {"tripartite.git_commit": workspace.commit}
    assert set(tags) - set(ours) == {"mlflow.runName"}


def test_every_param(workspace: Workspace) -> None:
    workspace.write_run()
    workspace.sync()

    assert only_run(workspace.mlruns_dir).data.params == EXPECTED_PARAMS


def test_every_metric_key_and_step(workspace: Workspace) -> None:
    workspace.write_run()
    workspace.sync()

    run = only_run(workspace.mlruns_dir)
    extras = {
        "tokens_input_mean": 1200.5,
        "tokens_output_mean": 1200.5,
        "latency_wall_ms_median": 1100.0,
        "parse_failure_rate": 1 - 25 / 27,
    }
    expected_keys = {f"{key}{suffix}" for key in OFFICIAL_KEYS for suffix in ("", "_mean", "_sd")}
    assert set(run.data.metrics) == expected_keys | set(extras)
    for key in OFFICIAL_KEYS:
        # one value per seed, at step = seed
        assert history(workspace.mlruns_dir, run, key) == [(0, 0.5), (1, 0.25), (2, 0.75)]
        assert history(workspace.mlruns_dir, run, f"{key}_mean") == [(0, 0.5)]
        assert history(workspace.mlruns_dir, run, f"{key}_sd") == [(0, 0.25)]
    for key, value in extras.items():
        assert history(workspace.mlruns_dir, run, key) == [(0, value)]


def test_null_values_are_skipped(workspace: Workspace) -> None:
    """``parse_failure_rate`` is null when nothing was parsed; ``_sd`` is null with one seed."""
    workspace.write_run(**one_seed_no_parses())
    workspace.sync()

    run = only_run(workspace.mlruns_dir)
    assert "parse_failure_rate" not in run.data.metrics
    assert set(run.data.metrics) == {
        f"{key}{suffix}" for key in OFFICIAL_KEYS for suffix in ("", "_mean")
    }
    assert run.data.params["seed_list"] == "[0]"


def test_the_artifacts_are_the_manifest_and_the_metrics_files_only(workspace: Workspace) -> None:
    run_dir = workspace.write_run()
    assert all((run_dir / name).exists() for name in samples.NEVER_SYNCED)
    workspace.sync()

    run = only_run(workspace.mlruns_dir)
    assert artifact_names(workspace.mlruns_dir, run) == [
        "manifest.json",
        "metrics.json",
        "metrics_seed0.json",
        "metrics_seed1.json",
        "metrics_seed2.json",
    ]
    stored = [p.name for p in workspace.mlruns_dir.rglob("*")]
    assert not any(
        name.startswith(("events", "plans_", "per_plan_", "blobs")) or name.endswith(".txt")
        for name in stored
    )
    artifact = next(workspace.mlruns_dir.rglob("artifacts/metrics.json"))
    assert artifact.read_bytes() == (run_dir / "metrics.json").read_bytes()


def test_the_sync_leaves_the_mlflow_environment_as_it_was(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "false")
    workspace.write_run()

    workspace.sync()

    assert "MLFLOW_ALLOW_FILE_STORE" not in os.environ
    assert os.environ["MLFLOW_DISABLE_TELEMETRY"] == "false"


# --- idempotency -------------------------------------------------------------------------------


def test_syncing_twice_gives_one_run(workspace: Workspace) -> None:
    workspace.write_run()

    first = workspace.sync()
    second = workspace.sync()

    run = only_run(workspace.mlruns_dir)
    assert run.info.run_id == second.mlflow_run_id != first.mlflow_run_id
    assert run.data.params == EXPECTED_PARAMS
    # the first one is deleted, not duplicated
    everything = runs(workspace.mlruns_dir, ViewType.ALL)
    assert sorted(r.info.lifecycle_stage for r in everything) == ["active", "deleted"]


def test_a_resync_replaces_only_its_own_run(workspace: Workspace) -> None:
    workspace.write_run()
    workspace.write_run(run_id=SECOND_RUN_ID)
    workspace.sync()
    other = workspace.sync(SECOND_RUN_ID)

    workspace.sync()

    by_tag = {r.data.tags["tripartite.run_id"]: r for r in runs(workspace.mlruns_dir)}
    assert set(by_tag) == {samples.RUN_ID, SECOND_RUN_ID}
    assert by_tag[SECOND_RUN_ID].info.run_id == other.mlflow_run_id


# --- single runs -------------------------------------------------------------------------------


def test_a_single_run_is_skipped(workspace: Workspace) -> None:
    run_dir = workspace.write_run(run_id=samples.OTHER_RUN_ID)
    (run_dir / "metrics.json").unlink()  # skipped before anything else is looked at

    result = workspace.sync(samples.OTHER_RUN_ID)

    assert (result.skipped, result.mlflow_run_id) == (True, None)
    assert not workspace.mlruns_dir.exists()


# --- errors: never a partial sync --------------------------------------------------------------


@pytest.mark.parametrize(
    "missing", ["metrics.json", "metrics_seed1.json", "manifest.json", "events.jsonl"]
)
def test_a_missing_file_is_an_error_and_nothing_is_written(
    workspace: Workspace, missing: str
) -> None:
    run_dir = workspace.write_run()
    (run_dir / missing).unlink()

    with pytest.raises(MlflowSyncError, match=re.escape(f"{missing} is missing")):
        workspace.sync()
    assert not workspace.mlruns_dir.exists()


def test_a_failed_resync_keeps_the_earlier_sync(workspace: Workspace) -> None:
    run_dir = workspace.write_run()
    first = workspace.sync()
    (run_dir / "metrics.json").unlink()

    with pytest.raises(MlflowSyncError, match=re.escape("metrics.json is missing")):
        workspace.sync()
    assert only_run(workspace.mlruns_dir).info.run_id == first.mlflow_run_id


def test_an_invalid_metrics_file_is_an_error(workspace: Workspace) -> None:
    run_dir = workspace.write_run()
    (run_dir / "metrics.json").write_text('{"schema_version": 1}\n')

    with pytest.raises(MlflowSyncError, match="not a valid Metrics"):
        workspace.sync()
    assert not workspace.mlruns_dir.exists()


def test_metrics_of_another_run_are_refused(workspace: Workspace) -> None:
    run_dir = workspace.write_run()
    other = samples.metrics(run_id=SECOND_RUN_ID)
    (run_dir / "metrics.json").write_text(other.model_dump_json())

    with pytest.raises(MlflowSyncError, match=f"belongs to run {SECOND_RUN_ID}"):
        workspace.sync()


@pytest.mark.parametrize("num_ctxs", [(), (32768, 16384)], ids=["no-calls", "two-values"])
def test_num_ctx_must_be_one_value(workspace: Workspace, num_ctxs: tuple[int, ...]) -> None:
    workspace.write_run(num_ctxs=num_ctxs)

    with pytest.raises(MlflowSyncError, match="one num_ctx"):
        workspace.sync()
    assert not workspace.mlruns_dir.exists()


@pytest.mark.parametrize(
    ("run_id", "message"),
    [(SECOND_RUN_ID, "no run"), ("../elsewhere", "is not a run id")],
    ids=["unknown", "malformed"],
)
def test_an_unknown_run_is_an_error(workspace: Workspace, run_id: str, message: str) -> None:
    workspace.write_run()

    with pytest.raises(MlflowSyncError, match=message):
        workspace.sync(run_id)


# --- tripartite.architecture_version -----------------------------------------------------------


def test_the_version_is_read_at_the_runs_commit_not_at_head(workspace: Workspace) -> None:
    workspace.write_run()
    later = "ARCHITECTURE.md · v0.13 · 2026-10-20\n"
    (workspace.repo / "ARCHITECTURE.md").write_text(later, encoding="utf-8")
    samples.git(workspace.repo, "commit", "--quiet", "--no-gpg-sign", "-am", "v0.13")
    head = samples.git(workspace.repo, "rev-parse", "HEAD")

    workspace.sync()

    tags = only_run(workspace.mlruns_dir).data.tags
    assert tags["tripartite.architecture_version"] == "v0.12"
    assert architecture_version(head, workspace.repo) == "v0.13"


def test_an_unreachable_commit_is_an_error_naming_it(workspace: Workspace) -> None:
    unknown = "c" * 40
    workspace.write_run(git_commit=unknown)

    with pytest.raises(MlflowSyncError, match=re.escape(f"ARCHITECTURE.md at commit {unknown}")):
        workspace.sync()
    assert not workspace.mlruns_dir.exists()


@pytest.mark.parametrize(
    "first_line",
    ["# Architecture", "ARCHITECTURE.md · 0.12 · 2026-10-07", "ARCHITECTURE.md v0.12", None],
    ids=["heading", "no-v", "no-separators", "no-file"],
)
def test_a_first_line_that_does_not_parse_is_an_error_naming_the_commit(
    tmp_path: Path, isolated_git: None, first_line: str | None
) -> None:
    commit = samples.write_git_repo(tmp_path / "other", first_line)

    with pytest.raises(MlflowSyncError, match=commit):
        architecture_version(commit, tmp_path / "other")


def test_a_commit_that_is_not_a_full_id_is_refused(workspace: Workspace) -> None:
    with pytest.raises(MlflowSyncError, match="'HEAD'"):
        architecture_version("HEAD", workspace.repo)
