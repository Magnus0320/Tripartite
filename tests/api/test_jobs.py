"""Start-up: a stale single run becomes ``interrupted``, with a ``run_end`` event (D7, D8)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import (
    batch_config,
    deps_for,
    open_stale_run,
    parse_sse,
    run_batch,
    run_to_end,
)
from tripartite.api.app import app
from tripartite.api.jobs import ApiSettings, sweep_stale_runs
from tripartite.config import RUNS_DIR, SINGLE_CONFIG_PATH
from tripartite.pipeline.lock import acquire_model_lock
from tripartite.pipeline.run import close_run, open_run, read_manifest
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import RUN_END_COUNT_KEYS, RunEndEvent


def _files(run_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(run_dir.iterdir()) if p.is_file()}


def test_the_default_settings_are_the_repository_runs_and_single_yaml() -> None:
    settings = ApiSettings()

    assert settings.runs_dir == RUNS_DIR
    assert settings.lock_path == RUNS_DIR / ".model.lock"
    assert settings.single_config_path == SINGLE_CONFIG_PATH
    assert settings.run_deps().runs_dir == RUNS_DIR


@pytest.mark.parametrize("queued", [False, True])
def test_a_stale_single_run_becomes_interrupted_with_a_run_end(
    settings: ApiSettings, queued: bool
) -> None:
    run_id = open_stale_run(settings, queued=queued)
    run_dir = settings.runs_dir / run_id
    assert read_manifest(run_dir).status == ("queued" if queued else "running")

    with TestClient(app) as client:
        manifest = read_manifest(run_dir)
        assert manifest.status == "interrupted"
        assert manifest.finished_at is not None
        assert manifest.error is not None
        assert manifest.error.type == "Interrupted"

        events = list(read_events(run_dir / "events.jsonl"))  # strict: the log is whole
        end = events[-1]
        assert isinstance(end, RunEndEvent)
        assert end.status == "interrupted"
        assert end.seq == len(events) - 1
        assert set(end.counts) == set(RUN_END_COUNT_KEYS)
        assert end.counts == {
            "queries": 1,
            "seeds": 1,
            "pairs_total": 1,
            "pairs_done": 0,
            "delivered": 0,
            "llm_calls": 0,
            "errors": 0,
        }
        assert end.metrics_path is None
        assert end.error == manifest.error

        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["status"] == "interrupted"
        assert detail["error"].startswith("Interrupted: ")
        assert detail["item"] is None
        stream = parse_sse(client.get(f"/api/runs/{run_id}/events").text)
        assert [name for name, _ in stream.events] == ["snapshot", "error"]

        assert run_to_end(client)["status"] == "succeeded"  # the sweep released the lock


def test_start_up_leaves_finished_runs_batch_runs_and_other_folders_alone(
    settings: ApiSettings,
) -> None:
    with TestClient(app) as client:
        finished = run_to_end(client)["run_id"]
    batch = run_batch(settings, ["val-001", "val-002"], [0])
    session = open_run(batch_config(["val-003", "val-004"], [0]), deps_for(settings))
    close_run(session)  # a batch run still marked running: the CLI's to resume, not the API's
    other = settings.runs_dir / "reproduce" / "a__b"
    other.mkdir(parents=True)
    (other / "reproduce_check.json").write_text("{}\n", encoding="utf-8")
    dirs = [settings.runs_dir / finished, settings.runs_dir / batch, session.run_dir, other]
    before = [_files(path) for path in dirs]

    with TestClient(app):
        pass

    assert [_files(path) for path in dirs] == before
    assert read_manifest(session.run_dir).status == "running"
    assert sweep_stale_runs(settings) == []


def test_nothing_is_swept_while_the_model_lock_is_held(settings: ApiSettings) -> None:
    run_id = open_stale_run(settings)
    before = _files(settings.runs_dir / run_id)

    lock = acquire_model_lock(settings.lock_path)  # some process is running a job right now
    try:
        with TestClient(app):
            pass
    finally:
        lock.release()

    assert _files(settings.runs_dir / run_id) == before
    assert sweep_stale_runs(settings) == [run_id]  # and it is swept once the lock is free


def test_start_up_without_a_runs_directory_creates_nothing(settings: ApiSettings) -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert not settings.runs_dir.exists()


def test_a_stale_run_with_a_partial_last_line_is_marked_but_never_repaired(
    settings: ApiSettings,
) -> None:
    run_id = open_stale_run(settings)
    events = settings.runs_dir / run_id / "events.jsonl"
    with events.open("ab") as file:
        file.write(b'{"schema_version": 1, "event_')  # the server died in the middle of a line
    log = events.read_bytes()

    with TestClient(app) as client:
        detail = client.get(f"/api/runs/{run_id}").json()

    assert events.read_bytes() == log
    assert [p.name for p in events.parent.glob("events.corrupt-*")] == []
    manifest = read_manifest(settings.runs_dir / run_id)
    assert manifest.status == "interrupted"
    assert manifest.error is not None
    assert "no run_end was written" in manifest.error.message
    assert detail["status"] == "interrupted"
    assert b'"run_end"' not in log


def test_a_folder_with_an_unreadable_manifest_is_skipped(settings: ApiSettings) -> None:
    broken = settings.runs_dir / "20260101T000000Z-single-0123abcd-0a0a"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    run_id = open_stale_run(settings)

    assert sweep_stale_runs(settings) == [run_id]
