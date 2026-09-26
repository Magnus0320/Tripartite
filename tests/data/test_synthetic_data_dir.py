"""FU-14: the shared synthetic set loads through ``TRIPARTITE_DATA_DIR`` alone (ARCHITECTURE.md D3).

This is exactly what other sessions' tests do: write the set, set the variable, call the loaders.
No fixture from this package is used and nothing in ``tripartite.data`` is monkeypatched.
"""

import csv
from pathlib import Path

import pytest

from tests.fixtures import synthetic_data
from tests.fixtures.synthetic_data import write_synthetic_data_dir
from tripartite.data import manifest
from tripartite.data.planner_inputs import get_planner_input, load_planner_inputs
from tripartite.evaluation.records import EVAL_COLUMNS, load_eval_records

ROWS = range(1, 181)


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
