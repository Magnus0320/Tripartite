"""EvalRecord and its loader (ARCHITECTURE.md D3), on synthetic files only (§8)."""

import builtins
import csv
import dataclasses
import json
from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.records import (
    EVAL_COLUMNS,
    INT_COLUMNS,
    EvalRecord,
    check_bridge_row,
    load_eval_records,
    parse_local_constraint,
    read_bridge_records,
    to_bridge_row,
    write_bridge_records,
)


def test_eval_record_carries_every_column() -> None:
    fields = [f.name for f in dataclasses.fields(EvalRecord)]

    assert fields.pop(fields.index("local_constraint") + 1) == "local_constraint_raw"  # FU-15
    assert tuple(fields) == ("query_id", *EVAL_COLUMNS)
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


# --- FU-15: the bridge records file (D5 §Bridge records file) --------------------------------


def _csv_cells(raw: Path) -> list[dict[str, str]]:
    """The cells of validation.csv, read here independently of the loader."""
    with (raw / "validation.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def assert_bridge_rows_reproduce_the_csv(raw: Path) -> None:
    """FU-15: every string field is the CSV cell byte for byte, every integer is int(cell)."""
    cells = _csv_cells(raw)
    records = load_eval_records()
    assert len(cells) == len(records) == 180
    for cell, record in zip(cells, records, strict=True):
        row = to_bridge_row(record)
        assert list(row) == list(EVAL_COLUMNS)  # exactly the 11 columns, no query_id
        for column in EVAL_COLUMNS:
            if column in INT_COLUMNS:
                assert type(row[column]) is int
                assert row[column] == int(cell[column])
            else:
                assert type(row[column]) is str
                assert str(row[column]).encode() == cell[column].encode()
        line = json.dumps(row, ensure_ascii=False)
        assert json.loads(line) == row


def test_bridge_rows_reproduce_every_csv_cell(synthetic_raw: Path) -> None:
    assert_bridge_rows_reproduce_the_csv(synthetic_raw)


@pytest.mark.usefixtures("synthetic_raw")
def test_local_constraint_raw_is_the_verbatim_cell_not_a_re_serialization() -> None:
    records = load_eval_records()

    assert records[0].local_constraint_raw == synthetic.LOCAL_CONSTRAINTS[1]
    assert records[1].local_constraint_raw == synthetic.LOCAL_CONSTRAINTS[0]
    for record in records:
        assert parse_local_constraint(record.local_constraint_raw) == record.local_constraint
        assert to_bridge_row(record)["local_constraint"] == record.local_constraint_raw


@pytest.mark.usefixtures("synthetic_raw")
def test_the_records_file_round_trips(tmp_path: Path) -> None:
    records = load_eval_records()
    path = tmp_path / "records.jsonl"

    write_bridge_records(records, path)

    data = path.read_bytes()
    assert data.count(b"\n") == 180
    assert data.endswith(b"\n")
    assert "ünïcødé ✈".encode() in data  # ensure_ascii=False
    assert read_bridge_records(path) == [to_bridge_row(r) for r in records]


@pytest.mark.usefixtures("synthetic_raw")
def test_a_records_file_of_another_length_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    write_bridge_records(load_eval_records()[:179], path)

    with pytest.raises(ValueError, match="179 rows, expected 180"):
        read_bridge_records(path)


@pytest.mark.usefixtures("synthetic_raw")
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"query_id": "val-001"}, "exactly the keys"),
        ({"days": "3"}, "days must be int"),
        ({"budget": True}, "budget must be int"),
        ({"local_constraint": {"house rule": None}}, "local_constraint must be str"),
    ],
)
def test_a_row_of_the_wrong_shape_is_refused(change: dict[str, object], message: str) -> None:
    row: dict[str, object] = {**to_bridge_row(load_eval_records()[0]), **change}

    with pytest.raises(ValueError, match=message):
        check_bridge_row(row)
