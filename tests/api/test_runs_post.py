"""``POST /api/runs`` and the job runner (D8, F2): one job at a time, through the pipeline."""

import dataclasses
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import (
    NO_VALIDATION_CSV,
    Gate,
    GatedClient,
    assert_no_absolute_path,
    run_to_end,
    start,
    wait_finished,
    with_deps,
)
from tripartite.api.app import app
from tripartite.api.jobs import ApiSettings, JobRunner, single_config
from tripartite.config import SINGLE_CONFIG_PATH, ConfigError, load_run_config
from tripartite.data.manifest import DATA_DIR
from tripartite.llm.errors import FakeModeRealDataError
from tripartite.pipeline.lock import acquire_model_lock
from tripartite.pipeline.run import read_manifest

RUN_ID = re.compile(r"\d{8}T\d{6}Z-single-[0-9a-f]{8}-[0-9a-f]{4}")


def _run_dirs(settings: ApiSettings) -> list[Path]:
    if not settings.runs_dir.exists():
        return []
    return [path for path in settings.runs_dir.iterdir() if path.is_dir()]


def _lock_is_free(settings: ApiSettings) -> bool:
    acquire_model_lock(settings.lock_path).release()
    return True


def test_a_run_is_accepted_as_queued_and_succeeds(
    client: TestClient, settings: ApiSettings
) -> None:
    response = client.post("/api/runs", json={"query_id": "val-002"})

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"run_id", "status"}
    assert body["status"] == "queued"
    assert RUN_ID.fullmatch(body["run_id"])

    detail = wait_finished(client, body["run_id"])
    assert detail["status"] == "succeeded"
    assert [path.name for path in _run_dirs(settings)] == [body["run_id"]]
    manifest = read_manifest(settings.runs_dir / body["run_id"])
    assert manifest.run_start.kind == "single"
    assert manifest.run_start.query_ids == ["val-002"]
    assert manifest.run_start.seeds == [0]  # the default seed
    assert manifest.run_start.model.runtime == "fake"


def test_the_config_is_single_yaml_with_only_queries_and_seeds_replaced(
    client: TestClient, settings: ApiSettings
) -> None:
    detail = run_to_end(client, "val-007", seed=3)

    stored = read_manifest(settings.runs_dir / detail["run_id"]).run_start.config
    committed = load_run_config(SINGLE_CONFIG_PATH).model_dump(mode="json")
    assert stored["queries"] == ["val-007"]
    assert stored["seeds"] == [3]
    assert {**stored, "queries": committed["queries"], "seeds": committed["seeds"]} == committed
    assert detail["item"]["seed"] == 3


def test_single_config_keeps_the_kind() -> None:
    config = single_config(SINGLE_CONFIG_PATH, "val-180", 5)

    assert (config.kind, config.queries, config.seeds) == ("single", ["val-180"], [5])


@pytest.mark.parametrize(
    "body", [{"query_id": "val-001", "seed": -1}, {"seed": 0}, {"query_id": "val-001", "x": 1}]
)
def test_an_invalid_body_is_422(
    client: TestClient, settings: ApiSettings, body: dict[str, object]
) -> None:
    assert client.post("/api/runs", json=body).status_code == 422
    assert _run_dirs(settings) == []


def test_an_unknown_query_id_is_404_and_starts_nothing(
    client: TestClient, settings: ApiSettings
) -> None:
    response = client.post("/api/runs", json={"query_id": "val-181"})

    assert response.status_code == 404
    assert "val-181" in response.json()["detail"]
    assert _run_dirs(settings) == []


def test_missing_data_is_503(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: ApiSettings
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    response = client.post("/api/runs", json={"query_id": "val-001"})

    assert response.status_code == 503
    assert response.json() == {"detail": NO_VALIDATION_CSV}
    assert_no_absolute_path(response.text, tmp_path)
    assert _run_dirs(settings) == []


def test_a_second_job_is_409_with_the_active_run_id_and_the_lock_is_released_after(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(app.state, "settings", with_deps(settings, client=GatedClient(gate)))
    with TestClient(app) as client:
        first = start(client)
        gate.wait_entered()

        response = client.post("/api/runs", json={"query_id": "val-002"})

        assert response.status_code == 409
        assert set(response.json()) == {"detail", "active_run_id"}
        assert response.json()["active_run_id"] == first
        assert [path.name for path in _run_dirs(settings)] == [first]

        gate.open()
        assert wait_finished(client, first)["status"] == "succeeded"
        assert run_to_end(client, "val-002")["status"] == "succeeded"
    assert _lock_is_free(settings)


def test_a_lock_held_elsewhere_is_409_with_no_active_run_id(
    client: TestClient, settings: ApiSettings
) -> None:
    lock = acquire_model_lock(settings.lock_path)  # as a CLI batch run would hold it
    try:
        response = client.post("/api/runs", json={"query_id": "val-001"})
    finally:
        lock.release()

    assert response.status_code == 409
    assert response.json()["active_run_id"] is None
    assert ".model.lock" in response.json()["detail"]
    assert _run_dirs(settings) == []
    assert run_to_end(client)["status"] == "succeeded"  # and free again once it is released


def test_without_a_calibration_the_real_model_path_is_503_and_nothing_exists(
    settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")  # the real model; the no_ollama guard forbids a call
    changed = with_deps(settings, calibration_path=tmp_path / "no-calibration.json")
    monkeypatch.setattr(app.state, "settings", changed)
    with TestClient(app) as client:
        response = client.post("/api/runs", json={"query_id": "val-001"})

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail.startswith("the run cannot start: CalibrationMissingError: ")
        assert "no-calibration.json" in detail
        assert_no_absolute_path(response.text, tmp_path)
        assert client.app.state.jobs.active_run_id is None  # type: ignore[attr-defined]
    assert _run_dirs(settings) == []
    assert _lock_is_free(settings)


def test_a_config_that_cannot_be_read_is_503_with_its_type_and_no_absolute_path(
    settings: ApiSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "configs" / "no-single.yaml"
    changed = dataclasses.replace(settings, single_config_path=missing)
    monkeypatch.setattr(app.state, "settings", changed)
    with pytest.raises(ConfigError) as raised:
        single_config(missing, "val-001", 0)
    with TestClient(app) as client:
        response = client.post("/api/runs", json={"query_id": "val-001"})

    assert str(missing) in str(raised.value)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail.startswith("the run cannot start: ConfigError: ")
    assert "no-single.yaml" in detail
    assert_no_absolute_path(response.text, tmp_path)
    assert _run_dirs(settings) == []
    assert _lock_is_free(settings)


def test_a_fake_mode_refusal_is_503_with_its_type_and_no_absolute_path(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: ApiSettings
) -> None:
    def refuse() -> None:
        raise FakeModeRealDataError(f"TRIPARTITE_DATA_DIR points at {DATA_DIR}; set it elsewhere")

    monkeypatch.setattr("tripartite.pipeline.run.require_synthetic_data_root", refuse)

    response = client.post("/api/runs", json={"query_id": "val-001"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "the run cannot start: FakeModeRealDataError: "
        "TRIPARTITE_DATA_DIR points at data; set it elsewhere"
    }
    assert_no_absolute_path(response.text, tmp_path)
    assert _run_dirs(settings) == []


@pytest.mark.asyncio
async def test_fake_mode_refuses_to_run_without_a_synthetic_data_root(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_DATA_DIR")  # FU-27, inherited through open_run

    with pytest.raises(FakeModeRealDataError, match="TRIPARTITE_DATA_DIR"):
        await JobRunner(settings).submit("val-001", 0)

    assert _run_dirs(settings) == []


def test_a_job_writes_the_d7_run_directory(client: TestClient, settings: ApiSettings) -> None:
    detail = run_to_end(client)

    run_dir = settings.runs_dir / detail["run_id"]
    names = {path.name for path in run_dir.iterdir()}
    assert {
        "manifest.json",
        "events.jsonl",
        "blobs",
        "plans_seed0.jsonl",
        "per_plan_eval_seed0.jsonl",
        "metrics_seed0.json",
        "metrics.json",
    } <= names
    types = [json.loads(line)["event_type"] for line in (run_dir / "events.jsonl").open()]
    assert types[0] == "run_start"
    assert types[-1] == "run_end"
    assert types.count("query_result") == 1
