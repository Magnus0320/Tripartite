"""``GET /api/runs/{run_id}``: every D8 field, filled from the run directory (F2)."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import (
    RICH_PLAN,
    Gate,
    GatedClient,
    responding,
    run_batch,
    run_to_end,
    start,
    wait_finished,
    with_deps,
)
from tests.fixtures import synthetic_data
from tripartite.api.app import app
from tripartite.api.history import attractions
from tripartite.api.jobs import ApiSettings
from tripartite.config import load_stack
from tripartite.evaluation.aggregate import LOCAL_CONSTRAINTS
from tripartite.evaluation.bridge_client import EvaluationError, FakeBridge, Plan
from tripartite.evaluation.constraints import COMMONSENSE_KEYS, HARD_KEYS, LABELS, PerPlanResult
from tripartite.evaluation.records import EvalRecord, load_eval_records
from tripartite.llm.errors import TransportError
from tripartite.llm.fake_client import FAKE_OUTPUT
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult
from tripartite.pipeline.run import read_manifest
from tripartite.runlog.schema import OfficialMetric

RUN_DETAIL = {
    "run_id",
    "kind",
    "status",
    "stage",
    "created_at",
    "finished_at",
    "config_hash",
    "model",
    "prompt_version",
    "error",
    "item",
    "summary",
}
ITEM_DETAIL = {
    "query_id",
    "seed",
    "query",
    "delivered",
    "failure_reason",
    "plan",
    "constraints",
    "commonsense_pass",
    "hard_pass",
    "final_pass",
    "usage",
    "raw_output",
}


def _events(settings: ApiSettings, run_id: str) -> list[dict[str, Any]]:
    path = settings.runs_dir / run_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _only(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    (event,) = [e for e in events if e["event_type"] == event_type]
    return event


def _with(settings: ApiSettings, monkeypatch: pytest.MonkeyPatch, **deps: Any) -> None:
    monkeypatch.setattr(app.state, "settings", with_deps(settings, **deps))


def test_a_succeeded_single_run_in_full(client: TestClient, settings: ApiSettings) -> None:
    detail = run_to_end(client, "val-004")

    manifest = read_manifest(settings.runs_dir / detail["run_id"])
    stack = load_stack()
    assert set(detail) == RUN_DETAIL
    assert detail["kind"] == "single"
    assert (detail["status"], detail["stage"]) == ("succeeded", "done")
    assert detail["created_at"] == manifest.created_at.isoformat().replace("+00:00", "Z")
    assert detail["finished_at"] is not None
    assert detail["finished_at"] >= detail["created_at"]
    assert detail["config_hash"] == manifest.run_start.config_hash
    assert detail["model"] == {"tag": stack.model.tag, "digest": stack.model.digest}
    assert detail["prompt_version"] == "sp-direct-v1"
    assert detail["error"] is None
    assert detail["summary"] is None

    item = detail["item"]
    assert set(item) == ITEM_DETAIL
    assert (item["query_id"], item["seed"]) == ("val-004", 0)
    assert item["query"] == synthetic_data.query(4)
    assert item["delivered"] is True
    assert item["failure_reason"] is None
    assert item["raw_output"] == FAKE_OUTPUT
    assert item["plan"] == [
        {
            "day": 1,
            "current_city": "-",
            "transportation": "-",
            "breakfast": "-",
            "attraction": "-",
            "attractions": [],
            "lunch": "-",
            "dinner": "-",
            "accommodation": "-",
        }
    ]
    assert (item["commonsense_pass"], item["hard_pass"], item["final_pass"]) == (True, True, True)


def test_usage_is_the_query_result_totals_plus_the_reported_total(
    client: TestClient, settings: ApiSettings
) -> None:
    detail = run_to_end(client)

    events = _events(settings, detail["run_id"])
    totals = _only(events, "query_result")["totals"]
    (call,) = [e for e in events if e["event_type"] == "llm_call" and e["role"] == "planner"]
    assert detail["item"]["usage"] == {
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "thinking_tokens": totals["thinking_tokens"],
        "load_ms": totals["load_ms"],
        "prefill_ms": totals["prefill_ms"],
        "generation_ms": totals["generation_ms"],
        "total_ms": call["timing_ms"]["total_reported"],
        "wall_ms": totals["wall_ms"],
    }
    assert detail["item"]["usage"]["output_tokens"] == len(FAKE_OUTPUT.encode())
    assert detail["item"]["usage"]["total_ms"] > 0


def test_the_13_constraints_in_eval_py_order_with_their_labels(client: TestClient) -> None:
    detail = run_to_end(client, "val-005")  # a hard query: every local constraint may count

    record = {r.query_id: r for r in load_eval_records("validation")}["val-005"]
    expected = [
        {
            "key": key,
            "label": LABELS[key],
            "group": "commonsense",
            "status": "pass",
            "message": None,
        }
        for key in COMMONSENSE_KEYS
    ]
    applicable = {
        check: record.local_constraint[key] is not None for key, check in LOCAL_CONSTRAINTS.items()
    }
    for key in HARD_KEYS:
        passed = key == "valid_cost" or applicable[key]
        status = "pass" if passed else "not_applicable"
        expected.append(
            {"key": key, "label": LABELS[key], "group": "hard", "status": status, "message": None}
        )
    assert detail["item"]["constraints"] == expected
    assert {row["status"] for row in expected} == {"pass", "not_applicable"}


class _Verdict(FakeBridge):
    """A bridge with one failing commonsense check and a message."""

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        result = super().per_plan(record, plan)
        assert result.commonsense is not None
        commonsense = {**result.commonsense, "is_valid_restaurants": (False, "Cafe One twice")}
        return PerPlanResult(record.query_id, result.delivered, commonsense, result.hard)


def test_a_failing_check_and_its_message(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with(settings, monkeypatch, bridge=_Verdict())
    with TestClient(app) as client:
        item = run_to_end(client)["item"]

    row = next(c for c in item["constraints"] if c["key"] == "is_valid_restaurants")
    assert row == {
        "key": "is_valid_restaurants",
        "label": "Diverse Restaurants",
        "group": "commonsense",
        "status": "fail",
        "message": "Cafe One twice",
    }
    assert (item["commonsense_pass"], item["hard_pass"], item["final_pass"]) == (False, True, False)
    assert item["delivered"] is True


def test_the_plan_day_by_day_with_attractions_split(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with(settings, monkeypatch, client=responding(RICH_PLAN))
    with TestClient(app) as client:
        item = run_to_end(client)["item"]

    assert item["raw_output"] == RICH_PLAN
    assert [day["day"] for day in item["plan"]] == [1, 2]
    first, second = item["plan"]
    assert first["current_city"] == "from Aville to Synthville"
    assert first["transportation"] == "Flight Number: F0000001, from Aville to Synthville"
    assert first["attraction"] == "Synth Museum, Synthville; Synth Park, Synthville;"
    assert first["attractions"] == ["Synth Museum, Synthville", "Synth Park, Synthville"]
    assert (first["lunch"], first["dinner"]) == ("Cafe One, Synthville", "Diner Two, Synthville")
    assert first["accommodation"] == "Cozy Room, Synthville"
    assert (second["breakfast"], second["attraction"], second["attractions"]) == (
        "Cafe One, Synthville",
        "-",
        [],
    )


@pytest.mark.parametrize(
    ("attraction", "expected"),
    [
        ("A, X; B, Y;", ["A, X", "B, Y"]),
        ("A, X", ["A, X"]),
        ("-", []),
        ("", []),
        (" ; - ;;  B, Y ", ["B, Y"]),
    ],
)
def test_attractions(attraction: str, expected: list[str]) -> None:
    assert attractions(attraction) == expected


def test_an_output_without_a_plan_is_undelivered(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with(settings, monkeypatch, client=responding("I cannot plan this trip."))
    with TestClient(app) as client:
        detail = run_to_end(client)

    item = detail["item"]
    assert detail["status"] == "succeeded"  # the run worked; the plan was not delivered
    assert item["delivered"] is False
    assert item["failure_reason"] == "no_day_blocks"
    assert item["plan"] is None
    assert item["raw_output"] == "I cannot plan this trip."
    assert [c["key"] for c in item["constraints"]] == [*COMMONSENSE_KEYS, *HARD_KEYS]
    assert {c["status"] for c in item["constraints"]} == {"not_evaluated"}
    assert (item["commonsense_pass"], item["hard_pass"], item["final_pass"]) == (False,) * 3


class _Down:
    """A client whose planner calls all fail in transport; the warm-up works."""

    def __init__(self) -> None:
        self._inner = responding("OK")

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if request.options.num_predict > 1:
            raise TransportError("connection refused")
        return self._inner.generate(request)


def test_when_every_call_fails_there_is_no_output_and_no_reported_time(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with(settings, monkeypatch, client=_Down())
    with TestClient(app) as client:
        detail = run_to_end(client)

    item = detail["item"]
    assert item["delivered"] is False
    assert item["failure_reason"] == "llm_error"
    assert item["plan"] is None
    assert item["raw_output"] == ""
    usage = item["usage"]
    assert [usage[k] for k in ("load_ms", "prefill_ms", "generation_ms", "total_ms")] == [None] * 4
    assert usage["output_tokens"] == 0
    assert usage["input_tokens"] > 0


class _Broken(FakeBridge):
    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        raise EvaluationError("KeyError", "the evaluator crashed")


def test_a_failed_run_has_its_error_and_no_item(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with(settings, monkeypatch, bridge=_Broken())
    with TestClient(app) as client:
        detail = run_to_end(client)
        again = run_to_end(client)  # the lock was released by the failed run

    assert detail["status"] == "failed"
    assert detail["stage"] == "evaluating"  # where it stopped
    assert detail["error"].startswith("EvaluationError: ")
    assert "the evaluator crashed" in detail["error"]
    assert detail["finished_at"] is not None
    assert detail["item"] is None
    assert again["status"] == "failed"


def test_a_running_run_has_no_item_yet(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    _with(settings, monkeypatch, client=GatedClient(gate))
    with TestClient(app) as client:
        run_id = start(client)
        gate.wait_entered()

        detail = client.get(f"/api/runs/{run_id}").json()

        assert (detail["status"], detail["stage"]) == ("running", "generating")
        assert detail["finished_at"] is None
        assert detail["item"] is None
        assert detail["error"] is None
        gate.open()
        assert wait_finished(client, run_id)["item"] is not None


def test_a_batch_run_has_a_summary_and_no_item(client: TestClient, settings: ApiSettings) -> None:
    run_id = run_batch(settings, ["val-001", "val-002", "val-003"], [0, 1])

    detail = client.get(f"/api/runs/{run_id}").json()

    assert set(detail) == RUN_DETAIL
    assert (detail["kind"], detail["status"], detail["stage"]) == ("batch", "succeeded", "done")
    assert detail["item"] is None
    summary = detail["summary"]
    assert summary["progress"] == {"done": 6, "total": 6}
    assert list(summary["metrics"]) == list(OfficialMetric.__args__)  # type: ignore[attr-defined]
    for value in summary["metrics"].values():
        assert set(value) == {"per_seed", "mean", "sd"}
        assert set(value["per_seed"]) == {"0", "1"}
    assert summary["metrics"]["Delivery Rate"] == {
        "per_seed": {"0": 1.0, "1": 1.0},
        "mean": 1.0,
        "sd": 0.0,
    }


def test_an_unscored_batch_run_has_empty_metrics(client: TestClient, settings: ApiSettings) -> None:
    run_id = run_batch(settings, ["val-001"], [0])
    (settings.runs_dir / run_id / "metrics.json").unlink()

    summary = client.get(f"/api/runs/{run_id}").json()["summary"]

    assert summary == {"progress": {"done": 1, "total": 1}, "metrics": {}}


@pytest.mark.parametrize(
    "run_id",
    [
        "20260101T000000Z-single-0123abcd-0a0a",  # well formed, but no such run
        "reproduce",  # a folder without a manifest (M5a's)
        "no-such-run",
        "..",
        "%2E%2E%2Fdata",
    ],
)
def test_an_unknown_run_id_is_404(client: TestClient, settings: ApiSettings, run_id: str) -> None:
    (settings.runs_dir / "reproduce" / "a__b").mkdir(parents=True)

    for path in (f"/api/runs/{run_id}", f"/api/runs/{run_id}/events"):
        response = client.get(path)

        assert response.status_code == 404, path
        assert set(response.json()) == {"detail"}


def test_a_run_whose_query_text_cannot_be_read_is_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    run_id = run_to_end(client)["run_id"]
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(tmp_path_factory.mktemp("empty")))

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 503
    assert set(response.json()) == {"detail"}


def test_no_evaluator_only_field_is_served(client: TestClient) -> None:
    detail = run_to_end(client, "val-009")

    text = client.get(f"/api/runs/{detail['run_id']}").text
    assert "CANARY_" not in text
    for canary in synthetic_data.canaries(9):
        assert canary not in text


def test_a_corrupt_log_of_a_succeeded_run_is_500_with_the_readers_message(
    client: TestClient, settings: ApiSettings
) -> None:
    run_id = run_to_end(client)["run_id"]
    events = settings.runs_dir / run_id / "events.jsonl"
    with events.open("ab") as file:
        file.write(b'{"schema_version": 1, "event_')
    log = events.read_bytes()

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 500
    assert "truncated line" in response.json()["detail"]
    assert events.read_bytes() == log
