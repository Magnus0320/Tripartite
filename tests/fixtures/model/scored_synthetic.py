"""A copy of the shared synthetic set that ``aggregate()`` can score (model; ARCHITECTURE.md D3).

The shared set (``tests/fixtures/synthetic_data.py``, data-eval) puts a canary in ``level`` and in
every row's ``local_constraint``, so ``aggregate()`` refuses it: a ``level`` must be easy, medium
or hard, and an easy query may carry no local constraint. D3 (v0.9) says code that feeds
synthetic rows into ``aggregate()`` or the metrics writer rewrites both in its own test setup and
never weakens the shared set. This module does exactly that, in its own temporary copy, with the
pattern of the real split:

- ``level`` becomes the real level the canary names (row ``i``: easy, medium or hard by
  ``i % 3``);
- ``local_constraint``: easy rows have none; medium rows keep the shared set's canary constraints
  except ``transportation`` (``eval.py`` counts no transportation check for a medium query, so a
  passing one would push hard micro above 1); hard rows keep all of the shared set's.

Every other column, including every other canary, is the shared set's.
"""

import ast
from pathlib import Path
from typing import Final

from tests.fixtures import synthetic_data

NO_CONSTRAINTS: Final = (
    "{'house rule': None, 'cuisine': None, 'room type': None, 'transportation': None}"
)


def level(i: int) -> str:
    return ("easy", "medium", "hard")[i % 3]


def local_constraint(i: int) -> str:
    if level(i) == "easy":
        return NO_CONSTRAINTS
    shared = synthetic_data.local_constraint(i)
    if level(i) == "hard":
        return shared
    constraint = ast.literal_eval(shared)
    constraint["transportation"] = None
    return repr(constraint)


def scored_row(i: int) -> dict[str, str]:
    row = synthetic_data.row(i)
    row["level"] = level(i)
    row["local_constraint"] = local_constraint(i)
    return row


def write_scored_synthetic_data_dir(root: Path) -> Path:
    """The shared set under ``root``, with ``validation.csv`` rewritten as above."""
    synthetic_data.write_synthetic_data_dir(root)
    rows = [scored_row(i) for i in range(1, synthetic_data.N + 1)]
    synthetic_data.write_csv(root / "raw" / "validation.csv", rows)
    return root
