"""The shared synthetic data set (data-eval; ARCHITECTURE.md D3 §Planner inputs in other
sessions' tests, D9, FU-14). Never rows of the real data (§8).

CI has no dataset. A test that needs ``PlannerInput``s or ``EvalRecord``s writes this set and
points ``TRIPARTITE_DATA_DIR`` at it, in its own ``conftest.py``::

    from tests.fixtures.synthetic_data import write_synthetic_data_dir

    @pytest.fixture(autouse=True)
    def synthetic_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(write_synthetic_data_dir(tmp_path)))

and then calls the loaders as usual. Nothing in ``tripartite.data`` is ever monkeypatched. Other
sessions import this module and never copy or edit it.

``write_synthetic_data_dir(root)`` writes ``raw/validation.csv`` (the 11 F7 columns, 180 rows)
and a matching ``raw/validation_ref_info.jsonl`` under ``root``, and returns ``root``. There is
no ``MANIFEST.json``: the loaders do not check it.

Canaries (D3 test 3, FU-16): every evaluator-only field except ``days`` holds a detectable
canary in every row. ``org``, ``dest``, ``level`` and the CSV's own ``reference_information``
column are ``CANARY_`` strings; ``date`` is a list literal with one ``CANARY_DATE_<iii>_<k>`` per
day; ``visiting_city_number``, ``people_number`` and ``budget`` are unique numbers of at least
eight digits (``visiting_city_number(i)``, ``people_number(i)``, ``budget(i)``); and
``local_constraint`` (``local_constraint(i)``) carries at least one ``CANARY_`` string in every
row while the rows vary which keys are ``None``: the odd rows set ``house rule``, ``cuisine`` and
``transportation``, the even rows only ``room type``, so each key is ``None`` in some rows and set
in others. ``canaries(i)`` lists all of them for row ``i`` (each ``CANARY_`` token, and the
numbers as decimal strings) plus the bare prefix ``CANARY_``; none of them occurs in any query or
reference line. ``days`` is excluded: the evaluator needs 3, 5 or 7, which no substring check can
detect, so D3 covers it structurally instead (the planner input has no ``days`` field, and the
prompt is a pure function of ``query`` and ``reference_information``).

The queries and reference lines carry quotes, commas, embedded newlines, odd spacing, tabs and
non-ASCII text, so byte-exactness is exercised too; ``query(i)`` and ``ref_line(i)`` give the
exact values of row ``i`` (from 1).
"""

import csv
import re
from pathlib import Path
from typing import Final

N: Final = 180
COLUMNS: Final = (
    "org",
    "dest",
    "days",
    "visiting_city_number",
    "date",
    "people_number",
    "local_constraint",
    "budget",
    "query",
    "level",
    "reference_information",
)
LOCAL_CONSTRAINT_ODD: Final = (
    "{'house rule': 'CANARY_RULE_7f3a', 'cuisine': ['CANARY_CUISINE_a', 'CANARY_CUISINE_b'], "
    "'room type': None, 'transportation': 'CANARY_TRANSPORT_7f3a'}"
)
CANARY: Final = re.compile(r"CANARY_\w+")
CANARY_STRING_COLUMNS: Final = (
    "org",
    "dest",
    "date",
    "local_constraint",
    "level",
    "reference_information",
)
CANARY_NUMBER_COLUMNS: Final = ("visiting_city_number", "people_number", "budget")


def query(i: int) -> str:
    return f'Synthetic query {i:03d}: a trip, "quoted", with commas,\nsecond line, ünïcødé ✈'


def ref_line(i: int) -> str:
    return f'{{"Attractions in Synthville {i:03d}":  "café №{i}",\t"Flights": [ {i}, "x" ]}}'


def budget(i: int) -> int:
    return 987_654_000 + i


def visiting_city_number(i: int) -> int:
    return 97_531_000 + i


def people_number(i: int) -> int:
    return 86_420_000 + i


def local_constraint(i: int) -> str:
    """Row ``i``'s ``local_constraint`` cell, a Python literal as in validation.csv."""
    if i % 2:
        return LOCAL_CONSTRAINT_ODD
    return (
        "{'house rule': None, 'cuisine': None, "
        f"'room type': 'CANARY_ROOM_even_{i:03d}', 'transportation': None}}"
    )


def row(i: int) -> dict[str, str]:
    """Row ``i`` (from 1) of the synthetic validation.csv."""
    days = (3, 5, 7)[(i - 1) % 3]
    return {
        "org": f"CANARY_ORG_{i:03d}",
        "dest": f"CANARY_DEST_{i:03d}",
        "days": str(days),
        "visiting_city_number": str(visiting_city_number(i)),
        "date": str([f"CANARY_DATE_{i:03d}_{k}" for k in range(1, days + 1)]),
        "people_number": str(people_number(i)),
        "local_constraint": local_constraint(i),
        "budget": str(budget(i)),
        "query": query(i),
        "level": f"CANARY_LVL_{('easy', 'medium', 'hard')[i % 3]}",
        "reference_information": f"CANARY_CSV_REF_{i:03d}",
    }


def canaries(i: int) -> list[str]:
    """Every value of row ``i`` that only the evaluator may see, as a substring to look for:
    each ``CANARY_`` token, each canary number as a decimal string, and the bare prefix."""
    cells = row(i)
    tokens = [t for column in CANARY_STRING_COLUMNS for t in CANARY.findall(cells[column])]
    return [*tokens, *(cells[column] for column in CANARY_NUMBER_COLUMNS), "CANARY_"]


def write_csv(path: Path, rows: list[dict[str, str]], header: tuple[str, ...] = COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(line.encode() + b"\n" for line in lines))


def write_raw(raw_dir: Path, n_rows: int = N, n_refs: int = N) -> None:
    write_csv(raw_dir / "validation.csv", [row(i) for i in range(1, n_rows + 1)])
    write_jsonl(raw_dir / "validation_ref_info.jsonl", [ref_line(i) for i in range(1, n_refs + 1)])


def write_synthetic_data_dir(root: Path) -> Path:
    """Write the full synthetic set under ``root`` and return the root for TRIPARTITE_DATA_DIR."""
    write_raw(root / "raw")
    return root
