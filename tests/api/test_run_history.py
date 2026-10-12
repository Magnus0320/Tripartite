"""``GET /api/runs``: the run history, from run directories in a temporary ``runs/`` (F3)."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import (
    Gate,
    GatedClient,
    assert_no_absolute_path,
    batch_config,
    corrupt_log,
    run_at,
    run_batch,
    run_to_end,
    start,
    wait_finished,
    with_deps,
)
from tripartite.api.app import app
from tripartite.api.jobs import ApiSettings
from tripartite.pipeline.run import read_manifest

RUN_SUMMARY = {
    "run_id",
    "kind",
    "status",
    "created_at",
    "query_id",
    "seed",
    "final_pass",
    "delivered",
    "headline",
}
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
ABSENT = "20260101T120002Z-single-ffffffff-0a0a"
"""A well-formed run id that names no run; it sorts just after the third run of ``_five``."""


def _five(settings: ApiSettings) -> list[str]:
    """Five single runs one second apart, newest first."""
    return [run_at(settings, T0 + timedelta(seconds=i)) for i in range(5)][::-1]


def _list(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/runs", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"items", "next_before"}
    return body


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["run_id"] for item in body["items"]]


def test_without_a_runs_directory_the_list_is_empty(
    client: TestClient, settings: ApiSettings
) -> None:
    assert _list(client) == {"items": [], "next_before": None}
    assert not settings.runs_dir.exists()


def test_runs_are_listed_newest_first(client: TestClient, settings: ApiSettings) -> None:
    newest_first = _five(settings)

    body = _list(client)

    assert _ids(body) == newest_first
    assert body["next_before"] is None
    created = [item["created_at"] for item in body["items"]]
    assert created == sorted(created, reverse=True)
    assert created[0] == "2026-01-01T12:00:04Z"


def test_runs_of_the_same_second_are_ordered_by_run_id(
    client: TestClient, settings: ApiSettings
) -> None:
    run_ids = [run_at(settings, T0) for _ in range(4)]

    assert _ids(_list(client)) == sorted(run_ids, reverse=True)
    assert _ids(_list(client, limit=3)) + _ids(_list(client, before=sorted(run_ids)[1])) == sorted(
        run_ids, reverse=True
    )


def test_paging_with_before_and_next_before(client: TestClient, settings: ApiSettings) -> None:
    newest_first = _five(settings)

    first = _list(client, limit=2)
    second = _list(client, limit=2, before=first["next_before"])
    third = _list(client, limit=2, before=second["next_before"])

    assert _ids(first) == newest_first[:2]
    assert first["next_before"] == newest_first[1]
    assert _ids(second) == newest_first[2:4]
    assert second["next_before"] == newest_first[3]
    assert _ids(third) == newest_first[4:]
    assert third["next_before"] is None


def test_a_page_that_ends_exactly_at_the_oldest_run_has_no_next(
    client: TestClient, settings: ApiSettings
) -> None:
    newest_first = _five(settings)

    body = _list(client, limit=5)

    assert _ids(body) == newest_first
    assert body["next_before"] is None
    assert _list(client, before=newest_first[-1]) == {"items": [], "next_before": None}


def test_the_default_limit_is_50_and_the_maximum_is_200(
    client: TestClient, settings: ApiSettings
) -> None:
    newest_first = _five(settings)
    parameters = {
        p["name"]: p["schema"] for p in app.openapi()["paths"]["/api/runs"]["get"]["parameters"]
    }

    assert parameters["limit"] == {
        "type": "integer",
        "maximum": 200,
        "minimum": 1,
        "default": 50,
        "title": "Limit",
    }
    assert _ids(_list(client, limit=200)) == newest_first
    assert _ids(_list(client, limit=1)) == newest_first[:1]


@pytest.mark.parametrize("limit", ["0", "-1", "201", "many", "1.5"])
def test_a_limit_out_of_range_is_422(client: TestClient, limit: str) -> None:
    assert client.get("/api/runs", params={"limit": limit}).status_code == 422


def test_an_unknown_but_well_formed_before_is_a_position(
    client: TestClient, settings: ApiSettings
) -> None:
    newest_first = _five(settings)

    assert _ids(_list(client, before=ABSENT)) == newest_first[2:]
    assert _ids(_list(client, before="20990101T000000Z-batch-0123abcd-0a0a")) == newest_first
    assert _ids(_list(client, before="20000101T000000Z-batch-0123abcd-0a0a")) == []


@pytest.mark.parametrize("before", ["", "no-such-run", "..", "reproduce", "2026", ABSENT + "0"])
def test_a_malformed_before_is_422(
    client: TestClient, settings: ApiSettings, before: str, tmp_path: Path
) -> None:
    _five(settings)

    response = client.get("/api/runs", params={"before": before})

    assert response.status_code == 422
    assert_no_absolute_path(response.text, tmp_path)


def test_both_kinds_are_in_one_list(client: TestClient, settings: ApiSettings) -> None:
    single = run_at(settings, T0)
    batch = run_at(
        settings, T0 + timedelta(seconds=1), batch_config(["val-001", "val-002"], [0, 1])
    )
    later = run_at(settings, T0 + timedelta(seconds=2))

    items = _list(client)["items"]

    assert [(item["run_id"], item["kind"]) for item in items] == [
        (later, "single"),
        (batch, "batch"),
        (single, "single"),
    ]
    for item in items:
        assert set(item) == RUN_SUMMARY
        assert item["status"] == "succeeded"


def test_a_single_run_fills_its_query_seed_and_verdict(
    client: TestClient, settings: ApiSettings
) -> None:
    detail = run_to_end(client, "val-004", seed=3)

    (item,) = _list(client)["items"]

    manifest = read_manifest(settings.runs_dir / detail["run_id"])
    assert item == {
        "run_id": detail["run_id"],
        "kind": "single",
        "status": "succeeded",
        "created_at": manifest.created_at.isoformat().replace("+00:00", "Z"),
        "query_id": "val-004",
        "seed": 3,
        "final_pass": detail["item"]["final_pass"],
        "delivered": detail["item"]["delivered"],
        "headline": None,
    }
    assert item["delivered"] is True


def test_a_single_run_in_progress_has_no_verdict_yet(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    monkeypatch.setattr(app.state, "settings", with_deps(settings, client=GatedClient(gate)))
    with TestClient(app) as client:
        run_id = start(client)
        gate.wait_entered()

        (item,) = _list(client)["items"]

        assert (item["run_id"], item["status"]) == (run_id, "running")
        assert (item["query_id"], item["seed"]) == ("val-001", 0)
        assert (item["delivered"], item["final_pass"], item["headline"]) == (None, None, None)
        gate.open()
        wait_finished(client, run_id)
        assert _list(client)["items"][0]["delivered"] is True


def test_a_batch_runs_headline_is_null_before_metrics_json_and_filled_after(
    client: TestClient, settings: ApiSettings
) -> None:
    run_id = run_batch(settings, ["val-001", "val-002", "val-003"], [0, 1])
    metrics = settings.runs_dir / run_id / "metrics.json"
    scored = metrics.read_bytes()
    metrics.unlink()

    (before,) = _list(client)["items"]
    metrics.write_bytes(scored)
    (after,) = _list(client)["items"]

    assert before["headline"] is None
    summary = client.get(f"/api/runs/{run_id}").json()["summary"]["metrics"]
    assert after["headline"] == {
        "final_pass_rate_mean": summary["Final Pass Rate"]["mean"],
        "delivery_rate_mean": summary["Delivery Rate"]["mean"],
    }
    assert after["headline"]["delivery_rate_mean"] == 1.0
    for item in (before, after):
        assert (item["kind"], item["status"]) == ("batch", "succeeded")
        assert [item[key] for key in ("query_id", "seed", "delivered", "final_pass")] == [None] * 4


def test_a_directory_without_a_manifest_is_skipped(
    client: TestClient, settings: ApiSettings
) -> None:
    run_id = run_at(settings, T0)
    other = settings.runs_dir / "reproduce" / "a__b"
    other.mkdir(parents=True)
    (other / "reproduce_check.json").write_text("{}\n", encoding="utf-8")
    (settings.runs_dir / "20270101T000000Z-single-0123abcd-0a0a").mkdir()  # no manifest
    (settings.runs_dir / "ollama-server.log").write_text("log\n", encoding="utf-8")
    named = settings.runs_dir / "not-a-run-id"
    named.mkdir()
    (named / "manifest.json").write_bytes(
        (settings.runs_dir / run_id / "manifest.json").read_bytes()
    )

    assert _ids(_list(client)) == [run_id]


def test_an_unreadable_manifest_is_skipped_and_does_not_shorten_the_page(
    client: TestClient, settings: ApiSettings
) -> None:
    newest_first = _five(settings)
    (settings.runs_dir / newest_first[1] / "manifest.json").write_text("{not json", "utf-8")

    body = _list(client, limit=2)

    assert _ids(body) == [newest_first[0], newest_first[2]]
    assert body["next_before"] == newest_first[2]
    assert _ids(_list(client, limit=4)) == [r for r in newest_first if r != newest_first[1]]
    assert _list(client, limit=4)["next_before"] is None


def test_a_corrupt_run_is_listed_without_its_result_and_does_not_break_the_list(
    client: TestClient,
    settings: ApiSettings,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    single = run_at(settings, T0)
    batch = run_at(settings, T0 + timedelta(seconds=1), batch_config(["val-001"], [0]))
    good = run_at(settings, T0 + timedelta(seconds=2))
    corrupt_log(settings, single)
    (settings.runs_dir / batch / "metrics.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="tripartite.api"):
        response = client.get("/api/runs")

    assert response.status_code == 200
    by_id = {item["run_id"]: item for item in response.json()["items"]}
    assert list(by_id) == [good, batch, single]
    assert by_id[good]["delivered"] is True
    assert by_id[batch]["headline"] is None
    assert (by_id[single]["delivered"], by_id[single]["final_pass"]) == (None, None)
    assert (by_id[single]["status"], by_id[single]["query_id"]) == ("succeeded", "val-001")
    assert_no_absolute_path(response.text, tmp_path)
    logged = [record.getMessage() for record in caplog.records]
    assert any(single in line for line in logged)
    assert any(batch in line for line in logged)
    assert client.get(f"/api/runs/{single}").status_code == 500  # its own route still says so


def test_the_list_needs_no_data_root(
    client: TestClient, settings: ApiSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = run_at(settings, T0)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    (item,) = _list(client)["items"]

    assert (item["run_id"], item["delivered"]) == (run_id, True)


def test_no_query_text_or_evaluator_only_value_is_listed(
    client: TestClient, settings: ApiSettings
) -> None:
    run_to_end(client, "val-009")
    run_batch(settings, ["val-009"], [0])

    text = client.get("/api/runs").text

    assert "CANARY_" not in text
