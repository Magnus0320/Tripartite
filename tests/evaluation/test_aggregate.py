"""``aggregate`` (ARCHITECTURE.md D5 §Wrapper) and the golden equivalence test.

The golden test is the CI step guarded by ``tests/fixtures/eval_golden/`` (D1): on the upstream
example submission, ``aggregate`` over the real bridge's per-plan results must equal the
official ``eval_score`` output exactly. The rest pin the subset rules on hand-built results.
"""

from collections import Counter
from dataclasses import replace

import pytest

from tests.evaluation import golden
from tests.evaluation.golden import GoldenQuery
from tripartite.evaluation.aggregate import aggregate, plan_pass
from tripartite.evaluation.bridge_client import fake_result
from tripartite.evaluation.constraints import COMMONSENSE_KEYS, PerPlanResult
from tripartite.runlog.schema import OFFICIAL_METRIC_KEYS

# --- the golden equivalence test -----------------------------------------------------------


def test_aggregate_equals_the_official_scores_on_the_example_submission() -> None:
    metrics = aggregate(golden.per_plan_results(), golden.queries())
    official = golden.official()

    assert set(official["scores"]) == set(OFFICIAL_METRIC_KEYS)
    assert metrics.scores == official["scores"]  # exact, not approximate
    assert metrics.detailed == official["detailed"]


def test_the_golden_fixtures_are_the_full_example_submission() -> None:
    results = golden.per_plan_results()  # parse_per_plan checks every result's shape (A-014)
    queries = golden.queries()

    assert [r.query_id for r in results] == [q.query_id for q in queries]
    assert [q.query_id for q in queries] == [f"val-{i:03d}" for i in range(1, 181)]
    assert sum(r.delivered for r in results) == 161  # F6
    assert golden.official()["scores"]["Delivery Rate"] == 161 / 180
    assert Counter((q.level, q.days) for q in queries) == dict.fromkeys(
        [(lvl, d) for lvl in ("easy", "medium", "hard") for d in (3, 5, 7)], 20
    )
    hard_evaluated = [r for r in results if r.hard is not None]
    assert hard_evaluated  # gating let some through, so the hard group is exercised
    assert any(v is None for r in hard_evaluated for v, _ in r.hard.values())  # type: ignore[union-attr]


def test_the_golden_denominators_are_eval_pys_constants() -> None:
    """With every plan passing everything, micro rates are 1: the denominators are 1440, 420."""
    queries = golden.queries()
    all_pass = [_passing(q) for q in queries]

    scores = aggregate(all_pass, queries).scores

    assert scores == dict.fromkeys(OFFICIAL_METRIC_KEYS, 1.0)
    applicable = sum(
        1 + sum(v is not None for k, v in q.local_constraint.items() if _counted(q.level, k))
        for q in queries
    )
    assert applicable == 420


# --- subsets, on hand-built results --------------------------------------------------------


def _counted(level: str, key: str) -> bool:
    return (level == "medium" and key != "transportation") or level == "hard"


def _query(i: int, level: str = "easy", days: int = 3, **constraints: str) -> GoldenQuery:
    local = {k: constraints.get(k.replace(" ", "_")) for k in golden.LOCAL_CONSTRAINT_KEYS}
    return GoldenQuery(query_id=f"val-{i:03d}", level=level, days=days, local_constraint=local)


def _passing(query: GoldenQuery) -> PerPlanResult:
    """Every commonsense check passed, every applicable hard check passed, the rest null."""
    return fake_result(query.query_id, dict(query.local_constraint), [{"days": 1}])


def _undelivered(query: GoldenQuery) -> PerPlanResult:
    return PerPlanResult(query_id=query.query_id, delivered=False, commonsense=None, hard=None)


def test_a_subset_uses_its_own_denominators() -> None:
    queries = [_query(1), _query(2, "hard", 5, house_rule="x", cuisine="y"), _query(3, "medium")]
    results = [_passing(queries[0]), _undelivered(queries[1]), _passing(queries[2])]

    scores = aggregate(results, queries).scores

    assert scores["Delivery Rate"] == 2 / 3
    assert scores["Commonsense Constraint Micro Pass Rate"] == 16 / 24
    # valid_cost for all three, plus house rule and cuisine for the hard query
    assert scores["Hard Constraint Micro Pass Rate"] == 2 / 5
    assert scores["Commonsense Constraint Macro Pass Rate"] == 2 / 3
    assert scores["Final Pass Rate"] == 2 / 3


def test_a_medium_transportation_pass_counts_in_the_numerator_only() -> None:
    """eval.py counts every true hard check, but a medium query's transportation constraint is
    not in the denominator (mapping_constraint_record, medium branch)."""
    query = _query(1, "medium", 3, transportation="no flight")
    scores = aggregate([_passing(query)], [query]).scores

    assert scores["Hard Constraint Micro Pass Rate"] == 2 / 1


def test_a_gated_plan_counts_for_no_macro_rate() -> None:
    query = _query(1)
    commonsense = dict.fromkeys(COMMONSENSE_KEYS, (True, None))
    commonsense["is_not_absent"] = (None, None)  # not a failure, but the hard group was skipped
    result = PerPlanResult(query.query_id, True, commonsense, None)

    scores = aggregate([result], [query]).scores

    assert plan_pass(result).commonsense is False  # eval.py's `continue` when hard is None
    assert scores["Commonsense Constraint Macro Pass Rate"] == 0.0
    assert scores["Commonsense Constraint Micro Pass Rate"] == 7 / 8
    assert scores["Hard Constraint Micro Pass Rate"] == 0.0


def test_plan_pass_fails_only_on_false() -> None:
    query = _query(1, "hard", 7, cuisine="x")
    base = _passing(query)
    assert plan_pass(base).final

    assert base.hard is not None
    assert base.commonsense is not None
    failed_hard = replace(base, hard={**base.hard, "valid_cuisine": (False, "no")})
    assert (plan_pass(failed_hard).commonsense, plan_pass(failed_hard).hard) == (True, False)
    failed = replace(base, commonsense={**base.commonsense, "is_valid_restaurants": (False, "x")})
    assert (plan_pass(failed).commonsense, plan_pass(failed).final) == (False, False)
    assert plan_pass(_undelivered(query)) == plan_pass(replace(base, commonsense=None))


def test_detailed_has_every_cell_and_eval_pys_totals() -> None:
    query = _query(1, "hard", 5, room_type="x")
    detailed = aggregate([_passing(query)], [query]).detailed

    assert set(detailed) == {"Commonsense Constraint", "Hard Constraint"}
    for group in detailed.values():
        assert {(lvl, day) for lvl in group for day in group[lvl]} == {
            (lvl, day) for lvl in ("easy", "medium", "hard") for day in ("3", "5", "7")
        }
    hard_cell = detailed["Hard Constraint"]["hard"]["5"]
    assert hard_cell["Budget"] == {"true": 1, "false": 0, "total": 1}
    assert hard_cell["Room Type"] == {"true": 1, "false": 0, "total": 1}
    assert hard_cell["Cuisine"] == {"true": 0, "false": 0, "total": 0}
    assert detailed["Commonsense Constraint"]["easy"]["3"] == {}


@pytest.mark.parametrize(
    ("results", "queries", "message"),
    [
        ([], [], "one result per query"),
        ([_undelivered(_query(1))], [_query(1), _query(2)], "one result per query"),
        ([_undelivered(_query(2))], [_query(1)], "is not for query val-001"),
        ([_undelivered(_query(1))], [_query(1, "expert")], "unexpected (level, days)"),
        ([_undelivered(_query(1))], [_query(1, days=4)], "unexpected (level, days)"),
        ([_undelivered(_query(1))], [_query(1, cuisine="x")], "an easy query with a 'cuisine'"),
    ],
)
def test_inputs_eval_py_would_reject_are_refused(
    results: list[PerPlanResult], queries: list[GoldenQuery], message: str
) -> None:
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        aggregate(results, queries)
