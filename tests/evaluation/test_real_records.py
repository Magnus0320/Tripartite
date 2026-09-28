"""The evaluator records on the real validation files after `make data` (local; D1, D5, FU-15)."""

import pytest
from typer.testing import CliRunner

from tests.evaluation.test_records import assert_bridge_rows_reproduce_the_csv
from tripartite.data import manifest
from tripartite.evaluation.cli import app
from tripartite.evaluation.records import load_eval_records

pytestmark = pytest.mark.local

# The output of `tripartite eval smoke-ids` on the pinned data, one per (level, days) cell.
SMOKE_IDS = {
    "val-001": ("easy", 3),
    "val-021": ("easy", 5),
    "val-041": ("easy", 7),
    "val-061": ("medium", 3),
    "val-081": ("medium", 5),
    "val-101": ("medium", 7),
    "val-121": ("hard", 3),
    "val-141": ("hard", 5),
    "val-161": ("hard", 7),
}


def test_bridge_rows_reproduce_every_real_csv_cell() -> None:
    assert_bridge_rows_reproduce_the_csv(manifest.raw_dir())


def test_smoke_ids_on_the_real_data() -> None:
    result = CliRunner().invoke(app, ["smoke-ids"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == list(SMOKE_IDS)
    records = load_eval_records()
    for query_id, cell in SMOKE_IDS.items():
        index = int(query_id[4:])
        assert (records[index - 1].level, records[index - 1].days) == cell
        assert all((r.level, r.days) != cell for r in records[: index - 1])
