"""``pipeline.metrics``: statistics, file formats and the run-log view (ARCHITECTURE.md D7, D5)."""

import json
import statistics
from pathlib import Path

import pytest

from tests.fixtures.model.run_deps import fake_deps
from tripartite.config import SMOKE_CONFIG_PATH
from tripartite.evaluation.bridge_client import FakeBridge
from tripartite.evaluation.constraints import COMMONSENSE_KEYS, HARD_KEYS, PerPlanResult
from tripartite.evaluation.records import load_eval_records
from tripartite.pipeline import metrics
from tripartite.pipeline.metrics import (
    AggregateMismatchError,
    PlanRow,
    _stats,
    _summary,
    is_full,
    load_run_log,
    per_plan_line,
    plans_for,
    plans_line,
    score_seed,
)
from tripartite.pipeline.run import start_run
from tripartite.runlog.reader import RunLogError


def test_stats_use_the_nearest_rank_p95() -> None:
    stats = _stats([float(v) for v in range(1, 21)])

    assert stats.p95 == 19.0  # index ceil(0.95 * 20) - 1 = 18
    assert stats.mean == 10.5
    assert stats.median == 10.5
    assert _stats([None, 3, None]).model_dump() == {"mean": 3.0, "median": 3.0, "p95": 3.0}
    assert _stats([]).model_dump() == {"mean": None, "median": None, "p95": None}
    assert _stats([None]).model_dump() == {"mean": None, "median": None, "p95": None}


def test_a_summary_has_the_sample_sd() -> None:
    two = _summary({0: 0.5, 2: 0.7})

    assert two.per_seed == {"0": 0.5, "2": 0.7}
    assert two.mean == pytest.approx(0.6)
    assert two.sd == statistics.stdev([0.5, 0.7])
    assert _summary({1: 0.25}).sd is None


def test_is_full() -> None:
    full = [f"val-{i:03d}" for i in range(1, 181)]

    assert is_full(full)
    assert not is_full(full[:-1])
    assert not is_full(list(reversed(full)))


def test_the_line_formats() -> None:
    plan = [{"days": 1, "lunch": "Café"}]
    assert plans_line(PlanRow(21, 'a "q"\nb', plan)) == (
        '{"idx": 21, "query": "a \\"q\\"\\nb", "plan": [{"days": 1, "lunch": "Café"}]}'
    )
    assert plans_line(PlanRow(3, "q", None)) == '{"idx": 3, "query": "q", "plan": null}'
    result = PerPlanResult(
        query_id="val-021",
        delivered=True,
        commonsense={key: (True, None) for key in reversed(COMMONSENSE_KEYS)},
        hard=None,
    )
    line = json.loads(per_plan_line(result))
    assert list(line) == ["idx", "query_id", "delivered", "commonsense", "hard"]
    assert list(line["commonsense"]) == list(COMMONSENSE_KEYS)  # key_dict order, always
    assert line["hard"] is None
    assert (line["idx"], line["query_id"]) == (21, "val-021")
    assert HARD_KEYS[0] == "valid_cost"


def test_score_seed_checks_the_bridge_against_aggregate(tmp_path: Path) -> None:
    records = load_eval_records()
    bridge = FakeBridge()
    plans = tmp_path / "plans.jsonl"
    plans.write_text(
        "".join(plans_line(PlanRow(i, "q", None)) + "\n" for i in range(1, 181)), "utf-8"
    )
    results = [bridge.per_plan(r, None) for r in records]

    scores, source = score_seed(results, records, plans_path=plans, bridge=bridge, full=True)
    assert source == "official_eval_score"
    assert scores.scores["Delivery Rate"] == 0.0

    class Off(FakeBridge):
        def aggregate(self, plans_path: Path, records_path: Path, set_type: str = "validation"):  # type: ignore[no-untyped-def]
            official = super().aggregate(plans_path, records_path, set_type)
            official.scores["Final Pass Rate"] += 2e-12
            return official

    with pytest.raises(AggregateMismatchError, match="Final Pass Rate"):
        score_seed(results, records, plans_path=plans, bridge=Off(), full=True)


def test_the_run_log_view_refuses_a_second_query_result(tmp_path: Path) -> None:
    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path))
    events = outcome.run_dir / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    result = next(line for line in lines if '"event_type":"query_result"' in line)
    data = json.loads(result)
    data["seq"] = len(lines)
    events.write_text("\n".join([*lines, json.dumps(data)]) + "\n", encoding="utf-8")

    with pytest.raises(RunLogError, match="a second query_result"):
        load_run_log(events)


def test_plans_are_checked_against_the_parse_events(tmp_path: Path) -> None:
    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path))
    view = load_run_log(outcome.run_dir / "events.jsonl")
    ids = view.run_start.query_ids
    texts = {q: "q" for q in ids}
    assert len(plans_for(view, 0, ids, texts)) == 9
    first = view.parses[(ids[0], 0)]
    view.parses[(ids[0], 0)] = first.model_copy(update={"n_days": 5})

    with pytest.raises(RunLogError, match="disagrees with its parse event"):
        plans_for(view, 0, ids, texts)


def test_every_non_delivery_reason_is_listed_even_at_zero() -> None:
    assert metrics.NON_DELIVERY_REASONS == (
        "llm_error",
        "empty_output",
        "length_no_plan",
        "no_day_blocks",
        "no_fields",
    )
