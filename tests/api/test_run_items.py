"""``GET /api/runs/{run_id}/items`` and ``…/items/{query_id}/{seed}`` (F3)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import (
    NO_VALIDATION_CSV,
    RICH_PLAN,
    Gate,
    GatedClient,
    assert_no_absolute_path,
    batch_config,
    corrupt_log,
    deps_for,
    responding,
    run_batch,
    run_to_end,
    start,
    wait_finished,
    with_deps,
)
from tests.fixtures import synthetic_data
from tripartite.api.app import app
from tripartite.api.jobs import ApiSettings
from tripartite.evaluation.bridge_client import FakeBridge, Plan
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest
from tripartite.pipeline.run import close_run, execute, open_run

ITEM_SUMMARY = {"query_id", "seed", "delivered", "final_pass", "commonsense_pass", "hard_pass"}
QUERIES = ["val-001", "val-002", "val-003"]
ABSENT = "20260101T000000Z-batch-0123abcd-0a0a"


def _items(client: TestClient, run_id: str, seed: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/runs/{run_id}/items", params={"seed": seed})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}
    items: list[dict[str, Any]] = body["items"]
    return items


def _not_found(client: TestClient, path: str, tmp_path: Path, **params: Any) -> str:
    response = client.get(path, params=params)
    assert response.status_code == 404, response.text
    assert set(response.json()) == {"detail"}
    assert_no_absolute_path(response.text, tmp_path)
    detail: str = response.json()["detail"]
    return detail


class FailingOne(FakeBridge):
    """The fake bridge, with one query's plan failing a commonsense check."""

    def __init__(self, query_id: str) -> None:
        super().__init__()
        self.query_id = query_id

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        result = super().per_plan(record, plan)
        if record.query_id != self.query_id or result.commonsense is None:
            return result
        commonsense = {**result.commonsense, "is_valid_restaurants": (False, "Cafe One twice")}
        return PerPlanResult(record.query_id, result.delivered, commonsense, result.hard)


# --- the item list -------------------------------------------------------------------------------


def test_the_items_of_each_seed_in_query_order(client: TestClient, settings: ApiSettings) -> None:
    run_id = run_batch(settings, ["val-003", "val-001", "val-002"], [0, 2])

    for seed in (0, 2):
        items = _items(client, run_id, seed)

        assert [(item["query_id"], item["seed"]) for item in items] == [(q, seed) for q in QUERIES]
        for item in items:
            assert set(item) == ITEM_SUMMARY
            detail = client.get(f"/api/runs/{run_id}/items/{item['query_id']}/{seed}").json()
            assert item == {key: detail[key] for key in ITEM_SUMMARY}
            assert item["delivered"] is True


def test_an_undelivered_and_a_failing_item(client: TestClient, settings: ApiSettings) -> None:
    def respond(request: GenerateRequest) -> str:
        return "no plan here" if synthetic_data.query(2) in request.prompt else RICH_PLAN

    deps = deps_for(
        settings,
        client=FakeClient(FakeTokenizer(), respond=respond),
        bridge=FailingOne("val-003"),
    )
    outcome = execute(open_run(batch_config(QUERIES, [0]), deps))
    assert outcome.status == "succeeded", outcome.error

    first, second, third = _items(client, outcome.run_id, 0)

    assert (first["delivered"], first["commonsense_pass"]) == (True, True)
    assert second == {
        "query_id": "val-002",
        "seed": 0,
        "delivered": False,
        "final_pass": False,
        "commonsense_pass": False,
        "hard_pass": False,
    }
    assert (third["delivered"], third["commonsense_pass"], third["final_pass"]) == (
        True,
        False,
        False,
    )


def test_a_run_in_progress_lists_what_is_finished_so_far(
    client: TestClient, settings: ApiSettings
) -> None:
    session = open_run(batch_config(QUERIES, [0]), deps_for(settings))
    close_run(session)  # opened and never executed: no pair has a result

    assert _items(client, session.run_id, 0) == []


def test_a_single_run_has_no_item_list(client: TestClient, tmp_path: Path) -> None:
    run_id = run_to_end(client)["run_id"]

    detail = _not_found(client, f"/api/runs/{run_id}/items", tmp_path, seed=0)

    assert detail == f"run {run_id} is a single run and has no item list"


def test_a_seed_the_run_does_not_have_is_404(
    client: TestClient, settings: ApiSettings, tmp_path: Path
) -> None:
    run_id = run_batch(settings, ["val-001"], [0, 2])

    detail = _not_found(client, f"/api/runs/{run_id}/items", tmp_path, seed=1)

    assert detail == f"run {run_id} has no seed 1"


@pytest.mark.parametrize("run_id", [ABSENT, "reproduce", "no-such-run", ".."])
def test_an_unknown_run_is_404_for_both_routes(
    client: TestClient, settings: ApiSettings, run_id: str, tmp_path: Path
) -> None:
    (settings.runs_dir / "reproduce" / "a__b").mkdir(parents=True)

    _not_found(client, f"/api/runs/{run_id}/items", tmp_path, seed=0)
    _not_found(client, f"/api/runs/{run_id}/items/val-001/0", tmp_path)


@pytest.mark.parametrize("params", [{}, {"seed": "-1"}, {"seed": "x"}, {"seed": "1.5"}])
def test_a_missing_or_invalid_seed_is_422(
    client: TestClient, settings: ApiSettings, params: dict[str, str]
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])

    assert client.get(f"/api/runs/{run_id}/items", params=params).status_code == 422


def test_a_corrupt_log_of_a_succeeded_run_is_500_for_both_routes(
    client: TestClient, settings: ApiSettings, tmp_path: Path
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])
    corrupt_log(settings, run_id)

    for path in (f"/api/runs/{run_id}/items?seed=0", f"/api/runs/{run_id}/items/val-001/0"):
        response = client.get(path)

        assert response.status_code == 500, path
        assert response.json()["detail"].startswith("the run log is corrupt: events.jsonl:")
        assert_no_absolute_path(response.text, tmp_path)


def test_a_half_written_last_line_of_an_unfinished_run_is_skipped(
    client: TestClient, settings: ApiSettings
) -> None:
    session = open_run(batch_config(QUERIES, [0]), deps_for(settings))
    close_run(session)
    corrupt_log(settings, session.run_id)
    log = (session.run_dir / "events.jsonl").read_bytes()

    assert _items(client, session.run_id, 0) == []
    assert (session.run_dir / "events.jsonl").read_bytes() == log  # never repaired


def test_the_item_list_needs_no_data_root(
    client: TestClient, settings: ApiSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = run_batch(settings, QUERIES, [0])
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    assert len(_items(client, run_id, 0)) == 3


# --- one item ------------------------------------------------------------------------------------


def test_the_item_of_a_single_run_equals_its_run_detail_item(client: TestClient) -> None:
    detail = run_to_end(client, "val-004", seed=3)

    response = client.get(f"/api/runs/{detail['run_id']}/items/val-004/3")

    assert response.status_code == 200
    assert response.json() == detail["item"]


def test_an_item_of_a_batch_run_in_full(
    client: TestClient, settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = run_batch(settings, QUERIES, [0, 1])
    monkeypatch.setattr(app.state, "settings", with_deps(settings, client=responding(RICH_PLAN)))

    item = client.get(f"/api/runs/{run_id}/items/val-002/1").json()

    with TestClient(app) as single_client:
        single = run_to_end(single_client, "val-002", seed=1)["item"]
    assert set(item) == set(single)
    assert (item["query_id"], item["seed"]) == ("val-002", 1)
    assert item["query"] == synthetic_data.query(2)
    assert item["delivered"] is True
    assert item["plan"] is not None
    assert [day["day"] for day in item["plan"]] == list(range(1, len(item["plan"]) + 1))
    assert len(item["constraints"]) == 13
    assert item["raw_output"]
    assert item["usage"]["input_tokens"] > 0
    assert item["usage"]["wall_ms"] >= 0


def test_each_pair_of_a_batch_run_is_its_own_item(
    client: TestClient, settings: ApiSettings
) -> None:
    run_id = run_batch(settings, QUERIES, [0, 1])

    for query_id in QUERIES:
        for seed in (0, 1):
            item = client.get(f"/api/runs/{run_id}/items/{query_id}/{seed}").json()

            assert (item["query_id"], item["seed"]) == (query_id, seed)
            assert item["query"] == synthetic_data.query(int(query_id[-3:]))


@pytest.mark.parametrize(
    ("query_id", "seed", "named"),
    [("val-004", "0", "('val-004', 0)"), ("val-001", "5", "('val-001', 5)"), ("nope", "0", "0)")],
)
def test_a_pair_the_run_does_not_have_is_404(
    client: TestClient, settings: ApiSettings, tmp_path: Path, query_id: str, seed: str, named: str
) -> None:
    run_id = run_batch(settings, QUERIES, [0, 1])

    detail = _not_found(client, f"/api/runs/{run_id}/items/{query_id}/{seed}", tmp_path)

    assert detail.startswith(f"run {run_id} has no item ")
    assert detail.endswith(named)


def test_a_pair_of_another_query_of_a_single_run_is_404(client: TestClient, tmp_path: Path) -> None:
    run_id = run_to_end(client)["run_id"]

    _not_found(client, f"/api/runs/{run_id}/items/val-002/0", tmp_path)
    _not_found(client, f"/api/runs/{run_id}/items/val-001/1", tmp_path)


def test_a_pair_without_a_result_yet_is_404(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = Gate()
    monkeypatch.setattr(app.state, "settings", with_deps(settings, client=GatedClient(gate)))
    with TestClient(app) as client:
        run_id = start(client)
        gate.wait_entered()

        detail = _not_found(client, f"/api/runs/{run_id}/items/val-001/0", tmp_path)

        assert detail == f"item ('val-001', 0) of run {run_id} has no result yet"
        gate.open()
        wait_finished(client, run_id)
        assert client.get(f"/api/runs/{run_id}/items/val-001/0").status_code == 200


@pytest.mark.parametrize("seed", ["x", "1.5"])
def test_a_seed_that_is_not_an_integer_is_422(
    client: TestClient, settings: ApiSettings, seed: str
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])

    assert client.get(f"/api/runs/{run_id}/items/val-001/{seed}").status_code == 422


def test_an_item_whose_query_text_cannot_be_read_is_503(
    client: TestClient, settings: ApiSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    response = client.get(f"/api/runs/{run_id}/items/val-001/0")

    assert response.status_code == 503
    assert response.json() == {"detail": NO_VALIDATION_CSV}
    assert_no_absolute_path(response.text, tmp_path)


def test_a_path_typed_into_the_url_does_not_come_back_absolute(
    client: TestClient, settings: ApiSettings, tmp_path: Path
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])
    typed = str(tmp_path / "data" / "raw" / "validation.csv").replace("/", "%2F")

    _not_found(client, f"/api/runs/{run_id}/items/{typed}/0", tmp_path)


def test_no_evaluator_only_field_is_served(client: TestClient, settings: ApiSettings) -> None:
    run_id = run_batch(settings, ["val-009"], [0])

    for path in (f"/api/runs/{run_id}/items?seed=0", f"/api/runs/{run_id}/items/val-009/0"):
        text = client.get(path).text
        assert "CANARY_" not in text
        for canary in synthetic_data.canaries(9):
            assert canary not in text
