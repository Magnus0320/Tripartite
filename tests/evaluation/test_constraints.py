"""``constraint_rows`` (ARCHITECTURE.md D5 §Wrapper, D8 ``Constraint``)."""

from collections import Counter

from tests.evaluation import golden
from tripartite.evaluation.constraints import (
    COMMONSENSE_KEYS,
    HARD_KEYS,
    LABELS,
    PerPlanResult,
    constraint_rows,
)

# eval.py::paper_term_mapping at e52c87f4, copied by hand.
PAPER_TERMS = {
    "is_valid_information_in_current_city": "Within Current City",
    "is_valid_information_in_sandbox": "Within Sandbox",
    "is_reasonable_visiting_city": "Reasonable City Route",
    "is_valid_restaurants": "Diverse Restaurants",
    "is_valid_transportation": "Non-conf. Transportation",
    "is_valid_attractions": "Diverse Attractions",
    "is_valid_accommodation": "Minimum Nights Stay",
    "is_not_absent": "Complete Information",
    "valid_cost": "Budget",
    "valid_room_rule": "Room Rule",
    "valid_cuisine": "Cuisine",
    "valid_room_type": "Room Type",
    "valid_transportation": "Transportation",
}


def test_the_labels_are_the_paper_terms() -> None:
    assert dict(LABELS) == PAPER_TERMS
    assert list(COMMONSENSE_KEYS) + list(HARD_KEYS) == list(PAPER_TERMS)


def test_there_are_always_eight_commonsense_then_five_hard_rows() -> None:
    for result in golden.per_plan_results():
        rows = constraint_rows(result)

        assert [r.key for r in rows] == [*COMMONSENSE_KEYS, *HARD_KEYS]
        assert [r.group for r in rows] == ["commonsense"] * 8 + ["hard"] * 5
        assert all(r.label == PAPER_TERMS[r.key] for r in rows)


def test_statuses_follow_the_values() -> None:
    result = PerPlanResult(
        query_id="val-001",
        delivered=True,
        commonsense={
            **dict.fromkeys(COMMONSENSE_KEYS, (True, None)),
            "is_valid_restaurants": (False, "The restaurant in day 1 breakfast is repeated."),
        },
        hard={**dict.fromkeys(HARD_KEYS, (None, None)), "valid_cost": (False, None)},
    )

    rows = {r.key: r for r in constraint_rows(result)}

    assert rows["is_not_absent"].status == "pass"
    assert rows["is_valid_restaurants"].status == "fail"
    assert rows["is_valid_restaurants"].message == "The restaurant in day 1 breakfast is repeated."
    assert rows["valid_cost"].status == "fail"
    assert rows["valid_cuisine"].status == "not_applicable"


def test_a_group_that_was_not_evaluated_is_not_evaluated() -> None:
    results = golden.per_plan_results()
    gated = next(r for r in results if r.delivered and r.hard is None)
    undelivered = next(r for r in results if not r.delivered)

    gated_rows = constraint_rows(gated)
    undelivered_rows = constraint_rows(undelivered)

    assert {r.status for r in gated_rows if r.group == "hard"} == {"not_evaluated"}
    assert "not_evaluated" not in {r.status for r in gated_rows if r.group == "commonsense"}
    assert {r.status for r in undelivered_rows} == {"not_evaluated"}
    assert {r.message for r in undelivered_rows} == {None}


def test_every_status_occurs_in_the_golden_results() -> None:
    statuses = Counter(r.status for res in golden.per_plan_results() for r in constraint_rows(res))

    assert set(statuses) == {"pass", "fail", "not_applicable", "not_evaluated"}
    assert sum(statuses.values()) == 180 * 13
