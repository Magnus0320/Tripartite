"""``tripartite eval``: evaluator-side commands (ARCHITECTURE.md D1, D5).

``smoke-ids`` prints the 9 query ids of the smoke run: one per (level, days) cell, easy/medium/
hard by 3/5/7, each the lowest-index query in its cell (D1, Phase 0 exit item 3). Selecting on
``level`` and ``days`` is an evaluator-side act, done once and offline; the model session
commits the output as explicit ``query_ids`` in ``configs/smoke.yaml``, and the planner never
sees those fields.
"""

from collections.abc import Iterable
from itertools import product
from typing import Final

import typer

from tripartite.data.manifest import DataError
from tripartite.evaluation.records import EvalRecord, load_eval_records

LEVELS: Final = ("easy", "medium", "hard")
DAYS: Final = (3, 5, 7)

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Evaluator-side commands."""


def smoke_query_ids(records: Iterable[EvalRecord]) -> list[str]:
    """The lowest-index query id of each of the 9 (level, days) cells, in query-id order."""
    first: dict[tuple[str, int], str] = {}
    for record in records:
        cell = (record.level, record.days)
        if record.level not in LEVELS or record.days not in DAYS:
            raise ValueError(f"{record.query_id} is in an unexpected (level, days) cell {cell}")
        first.setdefault(cell, record.query_id)
    missing = [cell for cell in product(LEVELS, DAYS) if cell not in first]
    if missing:
        raise ValueError(f"no query in the (level, days) cells {missing}")
    return sorted(first.values())


@app.command("smoke-ids")
def smoke_ids() -> None:
    """Print the 9 smoke-run query ids (one per (level, days) cell), one per line."""
    try:
        ids = smoke_query_ids(load_eval_records())
    except (DataError, OSError, ValueError) as exc:
        typer.echo(f"eval smoke-ids: {exc}", err=True)
        typer.echo("eval smoke-ids: FAILED", err=True)
        raise typer.Exit(1) from None
    for query_id in ids:
        typer.echo(query_id)
