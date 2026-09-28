"""The real bridge on the real evaluator, database and records (local; ARCHITECTURE.md D5).

Needs ``make setup`` and ``make data``. One bridge process serves the whole module, because
loading the database takes a few seconds.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.evaluation import generate_eval_golden, golden
from tripartite.evaluation.aggregate import aggregate
from tripartite.evaluation.bridge_client import (
    EVALUATION_DIR,
    EvaluationError,
    RealBridge,
    fake_result,
    read_plans,
)
from tripartite.evaluation.constraints import LABELS, PerPlanResult
from tripartite.evaluation.records import EvalRecord, load_eval_records, write_bridge_records

pytestmark = pytest.mark.local

# D5 §Confirmed from source: the six files the evaluator opens, relative to its cwd.
EVALUATOR_READS = (
    "../database/background/citySet_with_states.txt",
    "../database/flights/clean_Flights_2022.csv",
    "../database/accommodations/clean_accommodations_2022.csv",
    "../database/restaurants/clean_restaurant_2022.csv",
    "../database/googleDistanceMatrix/distance.csv",
    "../database/attractions/attractions.csv",
)


@pytest.fixture(scope="module")
def bridge() -> Iterator[RealBridge]:
    with RealBridge() as b:
        yield b


@pytest.fixture(scope="module")
def records() -> list[EvalRecord]:
    return load_eval_records()


@pytest.fixture(scope="module")
def records_path(records: list[EvalRecord], tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("bridge") / "records.jsonl"
    write_bridge_records(records, path)
    return path


def test_the_evaluator_finds_its_six_database_files() -> None:
    for relative in EVALUATOR_READS:
        assert (EVALUATION_DIR / relative).resolve().is_file(), relative


def test_the_golden_fixtures_regenerate_byte_identical(bridge: RealBridge, tmp_path: Path) -> None:
    generate_eval_golden.generate(tmp_path, bridge)

    for name in ("per_plan.jsonl", "official.json", "queries.jsonl", "provenance.json"):
        assert (tmp_path / name).read_bytes() == (golden.GOLDEN / name).read_bytes(), name


def test_the_golden_queries_match_the_real_records(records: list[EvalRecord]) -> None:
    lines = (golden.GOLDEN / "queries.jsonl").read_text(encoding="utf-8").splitlines()

    assert [json.loads(line) for line in lines] == [
        generate_eval_golden.query_json(r) for r in records
    ]


def test_the_real_denominators_are_eval_pys_constants(records: list[EvalRecord]) -> None:
    all_pass = [fake_result(r.query_id, r.local_constraint, [{"days": 1}]) for r in records]

    scores = aggregate(all_pass, records).scores

    assert set(scores.values()) == {1.0}  # 1440 commonsense and 420 hard checks, all passed


def _tallies(result: PerPlanResult) -> dict[str, dict[str, dict[str, int]]]:
    def count(group: dict[str, tuple[bool | None, str | None]] | None) -> dict[str, dict[str, int]]:
        return {
            k: {"true": list(v).count(True), "false": list(v).count(False)}
            for k, v in (group or {}).items()
        }

    return {
        "Commonsense Constraint": count(result.commonsense),
        "Hard Constraint": count(result.hard),
    }


def test_both_bridge_ops_agree_on_the_same_row(
    bridge: RealBridge, records: list[EvalRecord], records_path: Path, tmp_path: Path
) -> None:
    """D5: per_plan (the bridge converts local_constraint) and aggregate (eval.py converts it)
    must judge the same row identically. One delivered plan at a time, the rest null."""
    plans = read_plans(generate_eval_golden.PLANS)
    results = golden.per_plan_results()
    chosen = [
        next(r for r in results if r.hard is not None and records[_i(r)].level == level)
        for level in ("easy", "medium", "hard")
    ]
    chosen.append(next(r for r in results if r.delivered and r.hard is None))

    for expected in chosen:
        i = _i(expected)
        live = bridge.per_plan(records[i], plans[i])
        single = [None] * 180
        single[i] = plans[i]
        plans_path = tmp_path / f"single-{i}.jsonl"
        plans_path.write_text(
            "".join(json.dumps({"idx": n + 1, "plan": p}) + "\n" for n, p in enumerate(single))
        )

        official = bridge.aggregate(plans_path, records_path)

        assert live == expected
        record = records[i]
        for group, tally in _tallies(live).items():
            cell = official.detailed[group][record.level][str(record.days)]
            assert {k: {"true": v["true"], "false": v["false"]} for k, v in cell.items()} == {
                LABELS[k]: v for k, v in tally.items()
            }
        others = [
            PerPlanResult(r.query_id, False, None, None) if n != i else live
            for n, r in enumerate(records)
        ]
        assert aggregate(others, records).scores == official.scores


def test_the_real_bridge_refuses_the_test_split(bridge: RealBridge, records_path: Path) -> None:
    with pytest.raises(EvaluationError) as info:
        bridge._request(  # the client refuses first; this reaches the bridge itself
            "aggregate",
            set_type="test",
            plans_path=str(generate_eval_golden.PLANS),
            records_path=str(records_path),
        )

    assert info.value.error_type == "TestSplitForbiddenError"


def test_an_undelivered_plan_is_not_evaluated(
    bridge: RealBridge, records: list[EvalRecord]
) -> None:
    assert bridge.per_plan(records[0], None) == PerPlanResult("val-001", False, None, None)


def _i(result: PerPlanResult) -> int:
    return int(result.query_id[4:]) - 1
