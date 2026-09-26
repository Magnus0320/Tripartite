"""Synthetic validation files for the CI tests (ARCHITECTURE.md §8: never rows of the real data).

``write_raw`` writes a ``validation.csv`` with the 11 F7 columns and a matching
``validation_ref_info.jsonl``, all made up. Every evaluator-only text value holds a ``CANARY_``
string, and the budgets are canary numbers, so a test can prove none of them reaches a
``PlannerInput``. The queries and reference lines carry quotes, commas, embedded newlines, odd
spacing, tabs and non-ASCII text, so byte-exactness is exercised too.
"""

import csv
from pathlib import Path
from typing import Final

from tripartite.data import manifest

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
LOCAL_CONSTRAINTS: Final = (
    "{'house rule': None, 'cuisine': None, 'room type': None, 'transportation': None}",
    "{'house rule': 'CANARY_RULE_7f3a', 'cuisine': ['CANARY_CUISINE_a', 'CANARY_CUISINE_b'], "
    "'room type': None, 'transportation': 'CANARY_TRANSPORT_7f3a'}",
)


def query(i: int) -> str:
    return f'Synthetic query {i:03d}: a trip, "quoted", with commas,\nsecond line, ünïcødé ✈'


def ref_line(i: int) -> str:
    return f'{{"Attractions in Synthville {i:03d}":  "café №{i}",\t"Flights": [ {i}, "x" ]}}'


def budget(i: int) -> int:
    return 987_654_000 + i


def row(i: int) -> dict[str, str]:
    """Row ``i`` (from 1) of the synthetic validation.csv."""
    days = (3, 5, 7)[(i - 1) % 3]
    return {
        "org": f"CANARY_ORG_{i:03d}",
        "dest": f"CANARY_DEST_{i:03d}",
        "days": str(days),
        "visiting_city_number": str((i - 1) % 3 + 1),
        "date": str([f"2099-01-{d:02d}" for d in range(1, days + 1)]),
        "people_number": str((i - 1) % 8 + 1),
        "local_constraint": LOCAL_CONSTRAINTS[i % 2],
        "budget": str(budget(i)),
        "query": query(i),
        "level": f"CANARY_LVL_{('easy', 'medium', 'hard')[i % 3]}",
        "reference_information": f"CANARY_CSV_REF_{i:03d}",
    }


def canaries(i: int) -> list[str]:
    """The values of row ``i`` that only the evaluator may see."""
    values = [v for k, v in row(i).items() if k != "query" and "CANARY_" in v]
    return [*values, "CANARY_", str(budget(i))]


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


def matching_manifest(raw: Path) -> manifest.Manifest:
    """A manifest that records the files in ``raw`` and the current zip pin."""
    files = {
        name: manifest.FileEntry(
            bytes=(raw / name).stat().st_size, sha256=manifest.sha256_file(raw / name)
        )
        for name in manifest.HF_FILES
    }
    return manifest.Manifest(
        schema_version=1,
        dataset=manifest.Dataset(
            repo_id=manifest.HF_REPO_ID,
            repo_type=manifest.HF_REPO_TYPE,
            revision=manifest.HF_REVISION,
            files=files,
        ),
        database_zip=manifest.DATABASE_ZIP,
    )
