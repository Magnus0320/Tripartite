"""The evaluator's view of a validation query (ARCHITECTURE.md D3).

``EvalRecord`` carries every column of ``validation.csv``, including the evaluator-only fields
(``budget``, ``level``, ``local_constraint`` and the rest) that the planner must never see. It
lives here, on the evaluator side, and ``tripartite.data`` never imports it.

Values keep the types the official evaluator receives from ``datasets.load_dataset`` (F2): the
four integer columns become ``int``, and every other column stays the verbatim string, including
``date``. The one exception is ``local_constraint``, which is parsed into a dict with
``ast.literal_eval`` (never ``eval``); ``eval.py`` only parses it when it is still a string.

Only the validation split is ever loaded: ``"test"`` raises ``TestSplitForbiddenError`` and any
other split raises ``ValueError``, both before any file access.
"""

import ast
from dataclasses import dataclass
from typing import Final

from tripartite.data.manifest import N_VALIDATION, VALIDATION_CSV, raw_dir
from tripartite.data.planner_inputs import query_id_for, read_csv_rows, require_validation_split

EVAL_COLUMNS: Final = (
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
"""The columns of validation.csv at the pinned revision, in file order (F7)."""
INT_COLUMNS: Final = frozenset({"days", "visiting_city_number", "people_number", "budget"})

LocalConstraint = dict[str, str | list[str] | None]


@dataclass(frozen=True, slots=True)
class EvalRecord:
    query_id: str  # "val-001" … "val-180", the same ids as PlannerInput
    org: str
    dest: str
    days: int
    visiting_city_number: int
    date: str  # verbatim, e.g. "['2022-03-16', '2022-03-17', '2022-03-18']"
    people_number: int
    local_constraint: LocalConstraint
    budget: int
    query: str
    level: str
    reference_information: str  # the CSV column; the evaluator never reads it


def parse_local_constraint(text: str) -> LocalConstraint:
    """Parse a ``local_constraint`` cell as a Python literal. Code is never evaluated."""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
        raise ValueError(f"local_constraint is not a Python literal: {text!r}") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError(f"local_constraint is not a dict with string keys: {text!r}")
    for key, item in value.items():
        if not (
            item is None
            or isinstance(item, str)
            or (isinstance(item, list) and all(isinstance(x, str) for x in item))
        ):
            raise ValueError(f"local_constraint[{key!r}] has an unexpected value: {item!r}")
    return value


def _parse_int(column: str, text: str) -> int:
    if not text.isascii() or not text.isdigit():
        raise ValueError(f"{column} is not a non-negative integer: {text!r}")
    return int(text)


def _record(index: int, row: dict[str, str]) -> EvalRecord:
    ints = {c: _parse_int(c, row[c]) for c in INT_COLUMNS}
    return EvalRecord(
        query_id=query_id_for(index),
        org=row["org"],
        dest=row["dest"],
        days=ints["days"],
        visiting_city_number=ints["visiting_city_number"],
        date=row["date"],
        people_number=ints["people_number"],
        local_constraint=parse_local_constraint(row["local_constraint"]),
        budget=ints["budget"],
        query=row["query"],
        level=row["level"],
        reference_information=row["reference_information"],
    )


def load_eval_records(split: str = "validation") -> list[EvalRecord]:
    require_validation_split(split)
    header, rows = read_csv_rows(raw_dir() / VALIDATION_CSV)
    if tuple(header) != EVAL_COLUMNS:
        raise ValueError(f"{VALIDATION_CSV} has columns {header}, expected {list(EVAL_COLUMNS)}")
    if len(rows) != N_VALIDATION:
        raise ValueError(f"{VALIDATION_CSV} has {len(rows)} rows, expected {N_VALIDATION}")
    return [_record(i, row) for i, row in enumerate(rows, start=1)]
