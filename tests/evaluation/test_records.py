"""EvalRecord and its loader (ARCHITECTURE.md D3), on synthetic files only (§8)."""

import builtins
import dataclasses
from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.records import (
    EVAL_COLUMNS,
    EvalRecord,
    load_eval_records,
    parse_local_constraint,
)


def test_eval_record_carries_every_column() -> None:
    assert tuple(f.name for f in dataclasses.fields(EvalRecord)) == ("query_id", *EVAL_COLUMNS)
    assert EVAL_COLUMNS == synthetic.COLUMNS


@pytest.mark.usefixtures("synthetic_raw")
def test_records_keep_the_types_the_evaluator_receives() -> None:
    records = load_eval_records()

    assert len(records) == 180
    for i, record in enumerate(records, start=1):
        row = synthetic.row(i)
        assert record.query_id == f"val-{i:03d}"
        assert (record.org, record.dest, record.query, record.level) == (
            row["org"],
            row["dest"],
            row["query"],
            row["level"],
        )
        assert record.date == row["date"]  # verbatim, as load_dataset gives it
        assert record.reference_information == row["reference_information"]
        assert (record.days, record.visiting_city_number, record.people_number) == (
            int(row["days"]),
            int(row["visiting_city_number"]),
            int(row["people_number"]),
        )
        assert record.budget == synthetic.budget(i)
    assert records[0].local_constraint == {
        "house rule": "CANARY_RULE_7f3a",
        "cuisine": ["CANARY_CUISINE_a", "CANARY_CUISINE_b"],
        "room type": None,
        "transportation": "CANARY_TRANSPORT_7f3a",
    }
    assert records[1].local_constraint == dict.fromkeys(
        ("house rule", "cuisine", "room type", "transportation")
    )


@pytest.mark.usefixtures("synthetic_raw")
def test_records_and_planner_inputs_line_up() -> None:
    pairs = zip(load_eval_records(), load_planner_inputs(), strict=True)

    assert all((r.query_id, r.query) == (p.query_id, p.query) for r, p in pairs)


@pytest.mark.usefixtures("synthetic_raw")
def test_local_constraint_is_never_passed_to_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("eval() must never be called")

    monkeypatch.setattr(builtins, "eval", forbidden)

    assert len(load_eval_records()) == 180
    with pytest.raises(ValueError, match="not a Python literal"):
        parse_local_constraint("__import__('os').system('echo leaked')")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[1, 2]", "not a dict with string keys"),
        ("{1: None}", "not a dict with string keys"),
        ("{'budget': 1}", "unexpected value"),
        ("{'cuisine': ['a', 2]}", "unexpected value"),
        ("{'a': None", "not a Python literal"),
        ("", "not a Python literal"),
    ],
)
def test_malformed_local_constraints_are_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_local_constraint(text)


def test_a_different_header_is_refused(data_dir: Path) -> None:
    rows = [{**synthetic.row(i), "annotated_plan": "CANARY_PLAN"} for i in range(1, 181)]
    synthetic.write_csv(
        data_dir / "raw" / "validation.csv", rows, header=(*synthetic.COLUMNS, "annotated_plan")
    )

    with pytest.raises(ValueError, match="has columns"):
        load_eval_records()


@pytest.mark.parametrize("value", ["12.5", "-3", "", "1e3", "٣"])
def test_a_non_integer_in_an_integer_column_is_refused(data_dir: Path, value: str) -> None:
    rows = [synthetic.row(i) for i in range(1, 181)]
    rows[4]["budget"] = value
    synthetic.write_csv(data_dir / "raw" / "validation.csv", rows)

    with pytest.raises(ValueError, match="budget is not a non-negative integer"):
        load_eval_records()


def test_a_row_count_other_than_180_is_refused(data_dir: Path) -> None:
    synthetic.write_csv(data_dir / "raw" / "validation.csv", [synthetic.row(1)])

    with pytest.raises(ValueError, match="1 rows, expected 180"):
        load_eval_records()
