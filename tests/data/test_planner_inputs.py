"""PlannerInput and its loader (ARCHITECTURE.md D3), on synthetic files only (§8)."""

import dataclasses
from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data.planner_inputs import (
    PlannerInput,
    get_planner_input,
    load_planner_inputs,
    read_ref_info_lines,
)


def test_planner_input_fields() -> None:
    """D3 boundary test 1: the planner side has exactly these three fields."""
    assert {f.name for f in dataclasses.fields(PlannerInput)} == {
        "query_id",
        "query",
        "reference_information",
    }


def test_planner_input_is_frozen_and_slotted() -> None:
    inp = PlannerInput(query_id="val-001", query="q", reference_information="{}")
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.query = "changed"  # type: ignore[misc]
    assert not hasattr(inp, "__dict__")


@pytest.mark.usefixtures("synthetic_raw")
def test_loads_180_inputs_in_dataset_order() -> None:
    inputs = load_planner_inputs()

    assert [inp.query_id for inp in inputs] == [f"val-{i:03d}" for i in range(1, 181)]
    assert inputs[0].query_id == "val-001"
    assert inputs[-1].query_id == "val-180"
    assert all(type(inp) is PlannerInput for inp in inputs)


@pytest.mark.usefixtures("synthetic_raw")
def test_query_is_verbatim_and_reference_information_is_the_exact_line() -> None:
    inputs = load_planner_inputs()

    assert [inp.query for inp in inputs] == [synthetic.query(i) for i in range(1, 181)]
    assert [inp.reference_information for inp in inputs] == [
        synthetic.ref_line(i) for i in range(1, 181)
    ]


@pytest.mark.usefixtures("synthetic_raw")
def test_no_evaluator_only_value_reaches_a_planner_input() -> None:
    """The CSV's own reference_information column and every evaluator field are left out."""
    for i, inp in enumerate(load_planner_inputs(), start=1):
        text = repr(inp)
        for canary in synthetic.canaries(i):
            assert canary not in text


def test_reference_lines_keep_their_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "refs.jsonl"
    path.write_bytes(b'{"a":  1}\r\n{"b":\t"\xc3\xa9"}\n{"c": 3}')

    assert read_ref_info_lines(path) == ['{"a":  1}\r', '{"b":\t"é"}', '{"c": 3}']


def test_reference_lines_must_be_utf8(tmp_path: Path) -> None:
    path = tmp_path / "refs.jsonl"
    path.write_bytes(b'{"a": "\xff"}\n')

    with pytest.raises(UnicodeDecodeError):
        read_ref_info_lines(path)


def test_differing_row_counts_are_refused(data_dir: Path) -> None:
    synthetic.write_raw(data_dir / "raw", n_rows=180, n_refs=179)

    with pytest.raises(ValueError, match=r"180 rows but validation_ref_info\.jsonl has 179"):
        load_planner_inputs()


def test_a_row_count_other_than_180_is_refused(data_dir: Path) -> None:
    synthetic.write_raw(data_dir / "raw", n_rows=179, n_refs=179)

    with pytest.raises(ValueError, match="179 rows, expected 180"):
        load_planner_inputs()


def test_a_ragged_csv_row_is_refused(data_dir: Path) -> None:
    raw = data_dir / "raw"
    synthetic.write_raw(raw)
    with (raw / "validation.csv").open("a", encoding="utf-8") as f:
        f.write("only,three,fields\n")

    with pytest.raises(ValueError, match="row does not match the header"):
        load_planner_inputs()


def test_a_csv_without_a_query_column_is_refused(data_dir: Path) -> None:
    raw = data_dir / "raw"
    synthetic.write_raw(raw)
    header = tuple(c for c in synthetic.COLUMNS if c != "query")
    rows = [{k: v for k, v in synthetic.row(i).items() if k != "query"} for i in range(1, 181)]
    synthetic.write_csv(raw / "validation.csv", rows, header=header)

    with pytest.raises(ValueError, match="missing columns"):
        load_planner_inputs()


@pytest.mark.usefixtures("synthetic_raw")
def test_get_planner_input_returns_that_row() -> None:
    inp = get_planner_input("val-007")

    assert inp == PlannerInput(
        query_id="val-007", query=synthetic.query(7), reference_information=synthetic.ref_line(7)
    )


@pytest.mark.usefixtures("synthetic_raw")
@pytest.mark.parametrize("query_id", ["val-000", "val-181", "val-01", "val-0001", "foo", ""])
def test_get_planner_input_refuses_an_unknown_id(query_id: str) -> None:
    with pytest.raises(KeyError, match="unknown query_id"):
        get_planner_input(query_id)
