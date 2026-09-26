"""A-007: line i of validation_ref_info.jsonl belongs to row i of validation.csv (local).

Checked on the evaluator side only: the destination comes from ``EvalRecord.dest``, and nothing
here goes near the planner. For every row, some key of the reference-information object must
name the destination city or, when the destination is a state, one of that state's cities.
The city/state list is ``citySet_with_states.txt``, read in memory from the pinned sandbox
database zip after checking the zip against the D5 pin; nothing is extracted (unpacking is M2).

The second half of A-007, byte identity with ``database/validation_ref_info.jsonl`` in the
upstream repository at e52c87f4, is checked by git blob id, which is what GitHub reports for
that file. Comparing a sha256 instead would mean downloading the GitHub copy.
"""

import hashlib
import json
import zipfile
from collections import defaultdict
from typing import Any

import pytest

from tripartite.data import manifest
from tripartite.data.planner_inputs import read_ref_info_lines
from tripartite.evaluation.records import EvalRecord, load_eval_records

pytestmark = pytest.mark.local

# Git blob id of database/validation_ref_info.jsonl in OSU-NLP-Group/TravelPlanner at
# e52c87f4ac348a3410c46dc3553c519db5ec5e23 (GitHub contents API). The HF tree API reports the
# same oid for validation_ref_info.jsonl at 8736504ecfc31b7f8b7e40122873c337e83fff7c.
GITHUB_BLOB_ID = "e1be711528ea7fde30647b8a3e24ffe367fea82d"
CITY_STATE_ENTRY = "database/background/citySet_with_states.txt"


def _cities_by_state() -> dict[str, set[str]]:
    assert manifest.check_database_zip() == [], "run `make data` first"
    with zipfile.ZipFile(manifest.database_zip_path()) as archive:
        text = archive.read(CITY_STATE_ENTRY).decode("utf-8")
    cities: dict[str, set[str]] = defaultdict(set)
    for line in text.splitlines():
        if line:
            city, state = line.split("\t")
            cities[state].add(city)
    return cities


def _names_destination(
    ref: dict[str, Any], record: EvalRecord, cities: dict[str, set[str]]
) -> bool:
    names = {record.dest} | cities.get(record.dest, set())
    return any(name in key for key in ref for name in names)


def _misaligned(
    records: list[EvalRecord], refs: list[dict[str, Any]], cities: dict[str, set[str]]
) -> list[str]:
    return [
        r.query_id
        for r, ref in zip(records, refs, strict=True)
        if not _names_destination(ref, r, cities)
    ]


def test_each_reference_line_names_its_rows_destination() -> None:
    records = load_eval_records()
    refs = [
        json.loads(line)
        for line in read_ref_info_lines(manifest.raw_dir() / manifest.VALIDATION_REF_INFO)
    ]
    assert all(isinstance(ref, dict) for ref in refs)
    cities = _cities_by_state()

    assert _misaligned(records, refs, cities) == []
    # Not vacuous: shifting the lines by one breaks most rows (162 of 180 on the pinned data).
    assert len(_misaligned(records, refs[1:] + refs[:1], cities)) >= 150


def test_the_reference_file_is_byte_identical_to_the_upstream_copy() -> None:
    data = (manifest.raw_dir() / manifest.VALIDATION_REF_INFO).read_bytes()
    blob_id = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    assert blob_id == GITHUB_BLOB_ID
