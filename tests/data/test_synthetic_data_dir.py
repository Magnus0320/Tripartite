"""The shared synthetic set (ARCHITECTURE.md D3): FU-14 and FU-16.

FU-14: it loads through ``TRIPARTITE_DATA_DIR`` alone. This is exactly what other sessions' tests
do: write the set, set the variable, call the loaders. No fixture from this package is used and
nothing in ``tripartite.data`` is monkeypatched.

FU-16: every evaluator-only field except ``days`` carries a detectable canary on every row, and
``canaries(i)`` lists them all (D3 test 3). The columns come from the loader's own
``EVAL_COLUMNS``, not from the synthetic module.
"""

import ast
import csv
import re
from pathlib import Path

import pytest

from tests.fixtures import synthetic_data
from tests.fixtures.synthetic_data import write_synthetic_data_dir
from tripartite.data import manifest
from tripartite.data.planner_inputs import get_planner_input, load_planner_inputs
from tripartite.evaluation.records import EVAL_COLUMNS, load_eval_records, parse_local_constraint

ROWS = range(1, 181)
EVALUATOR_ONLY = [c for c in EVAL_COLUMNS if c != "query"]  # D3: the planner sees only query
CANARIED = [c for c in EVALUATOR_ONLY if c != "days"]  # D3 test 3 §Scope
NUMBERS = ("visiting_city_number", "people_number", "budget")


def test_both_loaders_read_the_synthetic_set_through_the_variable_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_synthetic_data_dir(tmp_path / "synthetic")
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))

    inputs = load_planner_inputs()
    records = load_eval_records()

    assert root == tmp_path / "synthetic"
    assert manifest.DATA_DIR == manifest.REPO_ROOT / "data"  # untouched: the variable did it
    ids = [f"val-{i:03d}" for i in ROWS]
    assert [inp.query_id for inp in inputs] == [r.query_id for r in records] == ids
    assert [inp.query for inp in inputs] == [synthetic_data.query(i) for i in ROWS]
    assert [inp.reference_information for inp in inputs] == [
        synthetic_data.ref_line(i) for i in ROWS
    ]
    assert [r.query for r in records] == [synthetic_data.query(i) for i in ROWS]
    assert [(r.org, r.budget) for r in records] == [
        (synthetic_data.row(i)["org"], synthetic_data.budget(i)) for i in ROWS
    ]
    assert get_planner_input("val-180").query == synthetic_data.query(180)


def test_the_synthetic_data_root_holds_the_two_raw_files_only(tmp_path: Path) -> None:
    root = write_synthetic_data_dir(tmp_path)

    assert root == tmp_path
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == [
        "raw",
        "raw/validation.csv",
        "raw/validation_ref_info.jsonl",
    ]
    with (root / "raw" / "validation.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames or ()) == EVAL_COLUMNS == synthetic_data.COLUMNS
        assert len(list(reader)) == 180
    assert (root / "raw" / "validation_ref_info.jsonl").read_bytes().count(b"\n") == 180


# --- FU-16: canaries (D3 test 3) --------------------------------------------------------------


def test_every_evaluator_only_field_but_days_carries_a_canary_on_every_row() -> None:
    assert len(CANARIED) == 9
    for i in ROWS:
        row = synthetic_data.row(i)
        found = [c for c in synthetic_data.canaries(i) if c != "CANARY_"]
        assert "CANARY_" in synthetic_data.canaries(i)
        for column in CANARIED:
            assert any(c in row[column] for c in found), (i, column)


def test_the_canary_numbers_are_unique_and_at_least_eight_digits() -> None:
    values = []
    for i in ROWS:
        row = synthetic_data.row(i)
        for column in NUMBERS:
            assert re.fullmatch(r"[0-9]{8,}", row[column]), (i, column)
            assert row[column] in synthetic_data.canaries(i), (i, column)
            values.append(row[column])
    assert len(set(values)) == len(values) == 3 * 180


def test_no_canary_occurs_in_any_query_or_reference_line() -> None:
    planner_text = "\0".join(
        [synthetic_data.query(j) for j in ROWS] + [synthetic_data.ref_line(j) for j in ROWS]
    )

    for i in ROWS:
        for canary in synthetic_data.canaries(i):
            assert canary not in planner_text, (i, canary)


def test_date_has_one_canary_per_day_and_days_stays_a_trip_length() -> None:
    for i in ROWS:
        row = synthetic_data.row(i)
        dates = ast.literal_eval(row["date"])
        assert row["days"] in {"3", "5", "7"}
        assert len(dates) == int(row["days"])
        assert all(d.startswith("CANARY_") and d in synthetic_data.canaries(i) for d in dates)


def test_every_local_constraint_has_a_canary_and_each_key_is_both_null_and_set() -> None:
    parsed = [parse_local_constraint(synthetic_data.row(i)["local_constraint"]) for i in ROWS]

    for constraint in parsed:
        assert any("CANARY_" in str(v) for v in constraint.values() if v is not None)
    for key in ("house rule", "cuisine", "room type", "transportation"):
        assert any(c[key] is None for c in parsed), key
        assert any(c[key] is not None for c in parsed), key
