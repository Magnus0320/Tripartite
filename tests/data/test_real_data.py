"""The real validation files after ``make data`` (local; ARCHITECTURE.md D3, D5)."""

import json

import pytest

from tripartite.data import manifest
from tripartite.data.planner_inputs import load_planner_inputs, read_ref_info_lines
from tripartite.evaluation.records import load_eval_records

pytestmark = pytest.mark.local


def test_the_data_on_disk_matches_every_pin() -> None:
    problems = {c.label: c.problems for c in manifest.verify() if not c.ok}

    assert problems == {}


def test_both_loaders_read_the_same_180_queries_in_the_same_order() -> None:
    inputs = load_planner_inputs()
    records = load_eval_records()

    assert len(inputs) == len(records) == 180
    assert [i.query_id for i in inputs] == [r.query_id for r in records]
    assert [i.query for i in inputs] == [r.query for r in records]


def test_reference_information_is_each_json_line_verbatim() -> None:
    lines = read_ref_info_lines(manifest.raw_dir() / manifest.VALIDATION_REF_INFO)

    assert [i.reference_information for i in load_planner_inputs()] == lines
    assert all(isinstance(json.loads(line), dict) for line in lines)
