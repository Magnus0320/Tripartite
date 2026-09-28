"""``tripartite eval smoke-ids`` (ARCHITECTURE.md D1, Phase 0 exit item 3), on synthetic files.

The synthetic set's own levels are canaries, so these tests write a copy whose ``level`` and
``days`` columns hold real cell values, laid out in blocks of 20 like the validation split but
in a shuffled cell order, so that "lowest index per cell" is not simply the first nine rows.
"""

from itertools import product
from pathlib import Path

from typer.testing import CliRunner

from tests.data import synthetic
from tripartite import cli as root_cli
from tripartite.evaluation.cli import DAYS, LEVELS, app

runner = CliRunner()
CELLS = list(product(LEVELS, DAYS))
BLOCK_ORDER = [CELLS[(b * 4) % 9] for b in range(9)]  # a permutation of the 9 cells


def _rows(cell_of_row: list[tuple[str, int]]) -> list[dict[str, str]]:
    rows = []
    for i, (level, days) in enumerate(cell_of_row, start=1):
        row = synthetic.row(i)
        row["level"] = level
        row["days"] = str(days)
        rows.append(row)
    return rows


def _write(data_dir: Path, cell_of_row: list[tuple[str, int]]) -> None:
    synthetic.write_raw(data_dir / "raw")
    synthetic.write_csv(data_dir / "raw" / "validation.csv", _rows(cell_of_row))


def test_one_lowest_index_query_per_cell_in_query_id_order(data_dir: Path) -> None:
    cell_of_row = [BLOCK_ORDER[(i - 1) // 20] for i in range(1, 181)]
    _write(data_dir, cell_of_row)

    result = runner.invoke(app, ["smoke-ids"])

    assert result.exit_code == 0, result.output
    ids = result.output.splitlines()
    assert ids == [f"val-{i:03d}" for i in range(1, 181, 20)]
    cells = [cell_of_row[int(query_id[4:]) - 1] for query_id in ids]
    assert sorted(cells) == sorted(CELLS)
    for query_id, cell in zip(ids, cells, strict=True):
        index = int(query_id[4:])
        assert cell not in cell_of_row[: index - 1]  # nothing earlier is in the same cell


def test_the_root_cli_reaches_smoke_ids(data_dir: Path) -> None:
    _write(data_dir, [CELLS[(i - 1) % 9] for i in range(1, 181)])

    result = runner.invoke(root_cli.app, ["eval", "smoke-ids"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [f"val-{i:03d}" for i in range(1, 10)]


def test_an_empty_cell_fails(data_dir: Path) -> None:
    _write(data_dir, [CELLS[(i - 1) % 8] for i in range(1, 181)])  # never ("hard", 7)

    result = runner.invoke(app, ["smoke-ids"])

    assert result.exit_code == 1
    assert "no query in the (level, days) cells [('hard', 7)]" in result.output
    assert result.output.splitlines()[-1] == "eval smoke-ids: FAILED"


def test_a_query_outside_the_nine_cells_fails(data_dir: Path) -> None:
    synthetic.write_raw(data_dir / "raw")  # the synthetic levels are canaries

    result = runner.invoke(app, ["smoke-ids"])

    assert result.exit_code == 1
    assert "val-001 is in an unexpected (level, days) cell" in result.output


def test_missing_data_fails_cleanly(data_dir: Path) -> None:
    result = runner.invoke(app, ["smoke-ids"])

    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "eval smoke-ids: FAILED"
