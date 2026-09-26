"""What the planner may see (ARCHITECTURE.md D3).

The planner path sees exactly ``query`` and ``reference_information``. ``PlannerInput`` is
built from an allowlist, so every other column of ``validation.csv``, including any added
later, never reaches it. The evaluator's view of a query is
``tripartite.evaluation.records.EvalRecord``; this package never imports it.

``query`` is the ``query`` column of ``validation.csv``, verbatim. ``reference_information`` is
line i of ``validation_ref_info.jsonl``, its exact bytes minus the trailing newline. The CSV's
own ``reference_information`` column is ignored, because the JSON file is the reference
information as JSON.

Only the validation split is ever loaded. ``"test"`` raises ``TestSplitForbiddenError`` and any
other split raises ``ValueError``, in both cases before any file or network access.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tripartite.data.manifest import N_VALIDATION, VALIDATION_CSV, VALIDATION_REF_INFO, raw_dir

PLANNER_COLUMNS: Final = ("query",)
"""The allowlist of validation.csv columns the planner side reads."""


@dataclass(frozen=True, slots=True)
class PlannerInput:
    query_id: str  # "val-001" … "val-180", 1-based dataset order
    query: str  # validation.csv column "query", verbatim
    reference_information: str  # validation_ref_info.jsonl line i, exact bytes minus trailing "\n"


class TestSplitForbiddenError(RuntimeError):
    """The test split is never loaded or downloaded (D3)."""

    __test__ = False  # not a pytest test class, despite the name


def require_validation_split(split: str) -> None:
    """Refuse every split but ``"validation"``. Call it before any I/O."""
    if isinstance(split, str) and split.strip().lower() == "test":
        raise TestSplitForbiddenError("the test split is never loaded (ARCHITECTURE.md D3)")
    if split != "validation":
        raise ValueError(f"unsupported split {split!r}: only 'validation' is used (D3)")


def query_id_for(index: int) -> str:
    """The query id of the ``index``-th row, counting from 1."""
    return f"val-{index:03d}"


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """The header and rows of a CSV file. Every row must have exactly the header's fields."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, strict=True)
        header = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"{path}:{reader.line_num}: row does not match the header")
            rows.append(row)
    return header, rows


def read_ref_info_lines(path: Path) -> list[str]:
    """Every line of a JSONL file, exact bytes minus the newline, decoded as strict UTF-8."""
    lines = path.read_bytes().split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return [line.decode("utf-8") for line in lines]


def load_planner_inputs(split: str = "validation") -> list[PlannerInput]:
    require_validation_split(split)
    directory = raw_dir()
    header, rows = read_csv_rows(directory / VALIDATION_CSV)
    missing = [c for c in PLANNER_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{VALIDATION_CSV}: missing columns {missing}")
    refs = read_ref_info_lines(directory / VALIDATION_REF_INFO)
    if len(rows) != len(refs):
        raise ValueError(
            f"{VALIDATION_CSV} has {len(rows)} rows but {VALIDATION_REF_INFO} has {len(refs)} lines"
        )
    if len(rows) != N_VALIDATION:
        raise ValueError(f"{VALIDATION_CSV} has {len(rows)} rows, expected {N_VALIDATION}")
    return [
        PlannerInput(query_id=query_id_for(i), query=row["query"], reference_information=ref)
        for i, (row, ref) in enumerate(zip(rows, refs, strict=True), start=1)
    ]


def get_planner_input(query_id: str) -> PlannerInput:
    for inp in load_planner_inputs():
        if inp.query_id == query_id:
            return inp
    raise KeyError(f"unknown query_id {query_id!r}; expected val-001 … val-{N_VALIDATION:03d}")
