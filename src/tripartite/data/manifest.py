"""Data pins, data paths and ``data/MANIFEST.json`` (ARCHITECTURE.md D3, D5, §6).

The pins are code constants here: the HF dataset revision with its two allowlisted files (D3),
and the sandbox database zip (D5 §Database — the pin; trust on first use, A-013).
``data/MANIFEST.json`` records the same revision, the size and sha256 of each HF file (written
by the first ``tripartite data fetch``, then committed), and the zip pin. A CI test asserts
that the zip pin here and in the manifest agree with each other and with the D5 table.

**The unpacked database** (D5 §Database — unpacking, M2). ``tripartite data fetch`` unpacks the
zip into ``vendor/travelplanner/database/`` (``VENDOR_DATABASE_DIR``), where the evaluator reads
it. The 8 expected files and their sizes are pinned here in code (``EXPECTED_DATABASE_FILES``);
their sha256 are recorded in the manifest under ``database_files`` on the first successful
unpack. They are fully determined by the pinned zip, so that is not a second trust decision.

``verify`` checks the files on disk against all of it; ``tripartite data verify`` prints the
result. A zip that differs from the pin is an architecture question, never a reason to update
the pin (A-013).

**``TRIPARTITE_DATA_DIR``** (D3 §Planner inputs in other sessions' tests). The data root is
``<repo>/data`` unless this environment variable is set. If it is set, it must be an absolute
path to an existing directory, and it replaces ``<repo>/data`` for every path below: ``raw/``
with the two dataset files, ``MANIFEST.json`` and ``downloads/sandbox_database.zip``. Any other
value raises ``DataError`` naming the variable. It is read at every call, never at import, so a
test can set it with ``monkeypatch.setenv``. The loaders do not check the manifest, so a tree
holding only ``raw/`` loads; ``tripartite data verify`` is the only thing that checks the pins.
Tests in other sessions point it at the shared synthetic set written by
``tests.fixtures.synthetic_data.write_synthetic_data_dir`` and never patch this module.
``DATA_DIR`` is only the default. The variable does not move ``VENDOR_DATABASE_DIR``.
"""

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, StringConstraints, ValidationError

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
DATA_DIR: Final = REPO_ROOT / "data"
"""The default data root, used when ``TRIPARTITE_DATA_DIR`` is unset. Call ``data_dir()``."""
DATA_DIR_ENV: Final = "TRIPARTITE_DATA_DIR"

HF_REPO_ID: Final = "osunlp/TravelPlanner"
HF_REPO_TYPE: Final = "dataset"
HF_REVISION: Final = "8736504ecfc31b7f8b7e40122873c337e83fff7c"
VALIDATION_CSV: Final = "validation.csv"
VALIDATION_REF_INFO: Final = "validation_ref_info.jsonl"
HF_FILES: Final[tuple[str, ...]] = (VALIDATION_CSV, VALIDATION_REF_INFO)
"""The download allowlist (D3). Nothing else is ever fetched from the dataset repository."""
N_VALIDATION: Final = 180

SCHEMA_VERSION: Final = 1

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DataError(RuntimeError):
    """The data files or the manifest do not match the pins, or the data root is invalid."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FileEntry(_Frozen):
    bytes: NonNegativeInt
    sha256: Sha256


class DatabaseZip(_Frozen):
    name: str
    bytes: NonNegativeInt
    sha256: Sha256


class Dataset(_Frozen):
    repo_id: str
    repo_type: str
    revision: str
    files: dict[str, FileEntry]


class Manifest(_Frozen):
    """``data/MANIFEST.json``: names, revisions, sizes and sha256 only (§8.1)."""

    schema_version: Literal[1]
    dataset: Dataset
    database_zip: DatabaseZip
    database_files: dict[str, FileEntry] | None = None
    """The unpacked database, by path under ``VENDOR_DATABASE_DIR``; absent until recorded."""


DATABASE_ZIP: Final = DatabaseZip(
    name="sandbox_database.zip",
    bytes=59_039_278,
    sha256="de345b0c243cd8c85355a264c5124db5db275327d2a38fa8685c6e69fabb650b",
)
"""The D5 pin: the user's first download, 2026-09-25 (A-013)."""

EXPECTED_DATABASE_FILES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "background/citySet_with_states.txt": 5_921,
        "background/citySet.txt": 3_064,
        "background/stateSet.txt": 642,
        "attractions/attractions.csv": 817_982,
        "flights/clean_Flights_2022.csv": 304_807_007,
        "googleDistanceMatrix/distance.csv": 795_427,
        "restaurants/clean_restaurant_2022.csv": 683_023,
        "accommodations/clean_accommodations_2022.csv": 520_458,
    }
)
"""The 8 files the pinned zip unpacks to, path under ``VENDOR_DATABASE_DIR`` -> bytes (D5)."""

VENDOR_DATABASE_DIR: Final = REPO_ROOT / "vendor" / "travelplanner" / "database"
"""Where the evaluator reads the database: ``../database/`` from its cwd (D5, F1)."""

DATABASE_ZIP_HOWTO: Final = (
    "download it by hand from the Google Drive link in the upstream TravelPlanner README and "
    "save it, unrenamed, as data/downloads/sandbox_database.zip (D5)"
)


def data_dir() -> Path:
    """``$TRIPARTITE_DATA_DIR`` if set, else ``DATA_DIR``. Read at every call, never cached."""
    value = os.environ.get(DATA_DIR_ENV)
    if value is None:
        return DATA_DIR
    path = Path(value)
    if not path.is_absolute():
        raise DataError(f"{DATA_DIR_ENV} must be an absolute path, got {value!r}")
    if not path.is_dir():
        raise DataError(f"{DATA_DIR_ENV} must be an existing directory, got {value!r}")
    return path


def raw_dir() -> Path:
    return data_dir() / "raw"


def manifest_path() -> Path:
    return data_dir() / "MANIFEST.json"


def database_zip_path() -> Path:
    return data_dir() / "downloads" / DATABASE_ZIP.name


def vendor_database_dir() -> Path:
    return VENDOR_DATABASE_DIR


def display(path: Path) -> str:
    """``path`` relative to the repository root when it is inside it, for messages."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_manifest(path: Path) -> Manifest:
    try:
        return Manifest.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        raise DataError(f"{display(path)}: missing; run `tripartite data fetch`") from None
    except ValidationError as exc:
        raise DataError(f"{display(path)}: invalid: {exc}") from None


def write_manifest(manifest: Manifest, path: Path) -> None:
    """Write ``manifest`` atomically, with sorted keys so that diffs stay stable."""
    data = manifest.model_dump(mode="json", exclude_none=True)
    text = json.dumps(data, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def check_file(path: Path, expected_bytes: int, expected_sha256: str | None) -> list[str]:
    """What is wrong with ``path`` against an expected size and sha256; empty if nothing.

    With ``expected_sha256`` None, only the size is checked.
    """
    if not path.is_file():
        return ["missing"]
    size = path.stat().st_size
    if size != expected_bytes:
        return [f"expected {expected_bytes} bytes, found {size}"]
    if expected_sha256 is None:
        return []
    actual = sha256_file(path)
    if actual != expected_sha256:
        return [f"expected sha256 {expected_sha256}, found {actual}"]
    return []


def manifest_pin_problems(manifest: Manifest) -> list[str]:
    """Where ``manifest`` disagrees with the pins in this module."""
    problems = []
    dataset = manifest.dataset
    for field, actual, expected in (
        ("dataset.repo_id", dataset.repo_id, HF_REPO_ID),
        ("dataset.repo_type", dataset.repo_type, HF_REPO_TYPE),
        ("dataset.revision", dataset.revision, HF_REVISION),
    ):
        if actual != expected:
            problems.append(f"{field} is {actual!r}, expected {expected!r}")
    if sorted(dataset.files) != sorted(HF_FILES):
        problems.append(f"dataset.files lists {sorted(dataset.files)}, expected {sorted(HF_FILES)}")
    if manifest.database_zip != DATABASE_ZIP:
        problems.append(
            f"database_zip is {manifest.database_zip.model_dump()}, expected the D5 pin "
            f"{DATABASE_ZIP.model_dump()}"
        )
    if manifest.database_files is not None:
        if sorted(manifest.database_files) != sorted(EXPECTED_DATABASE_FILES):
            problems.append(
                f"database_files lists {sorted(manifest.database_files)}, expected "
                f"{sorted(EXPECTED_DATABASE_FILES)}"
            )
        problems.extend(
            f"database_files[{path!r}] is {entry.bytes} bytes, expected "
            f"{EXPECTED_DATABASE_FILES[path]}"
            for path, entry in sorted(manifest.database_files.items())
            if path in EXPECTED_DATABASE_FILES and entry.bytes != EXPECTED_DATABASE_FILES[path]
        )
    return problems


def check_database_zip() -> list[str]:
    """What is wrong with the zip on disk against the D5 pin; empty if nothing."""
    path = database_zip_path()
    if not path.is_file():
        return [f"missing: {DATABASE_ZIP_HOWTO}"]
    problems = check_file(path, DATABASE_ZIP.bytes, DATABASE_ZIP.sha256)
    return [
        f"{p}; a zip that differs from the D5 pin is an architecture question (A-013), "
        "never a reason to update the pin"
        for p in problems
    ]


@dataclass(frozen=True)
class Check:
    """One line of ``tripartite data verify``: what was checked, and what is wrong with it."""

    label: str
    detail: str
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def verify() -> list[Check]:
    """Check the manifest, the HF files and the zip against the pins, collecting every problem."""
    checks = []
    mpath = manifest_path()
    manifest: Manifest | None = None
    try:
        manifest = load_manifest(mpath)
    except DataError as exc:
        checks.append(Check(display(mpath), "", (str(exc).removeprefix(f"{display(mpath)}: "),)))
    if manifest is not None:
        checks.append(
            Check(
                display(mpath),
                f"{manifest.dataset.repo_id}@{manifest.dataset.revision}",
                tuple(manifest_pin_problems(manifest)),
            )
        )
        for name in HF_FILES:
            entry = manifest.dataset.files.get(name)
            if entry is None:
                continue
            checks.append(
                Check(
                    display(raw_dir() / name),
                    f"{entry.bytes} bytes, sha256 {entry.sha256}",
                    tuple(check_file(raw_dir() / name, entry.bytes, entry.sha256)),
                )
            )
    checks.append(
        Check(
            display(database_zip_path()),
            f"{DATABASE_ZIP.bytes} bytes, sha256 {DATABASE_ZIP.sha256}, the D5 pin",
            tuple(check_database_zip()),
        )
    )
    recorded = manifest.database_files if manifest is not None else None
    checks.extend(check_database_files(recorded))
    return checks


def check_database_files(recorded: Mapping[str, FileEntry] | None) -> list[Check]:
    """One check per unpacked database file: its size in code, and its sha256 once recorded."""
    checks = []
    for path, size in EXPECTED_DATABASE_FILES.items():
        file = vendor_database_dir() / path
        entry = recorded.get(path) if recorded is not None else None
        sha256 = entry.sha256 if entry is not None else None
        problems = check_file(file, size, sha256)
        detail = (
            f"{size} bytes, sha256 {sha256}" if sha256 else f"{size} bytes; sha256 not recorded yet"
        )
        if problems == ["missing"]:
            problems = ["missing; run `tripartite data fetch` to unpack the database"]
        checks.append(Check(display(file), detail, tuple(problems)))
    return checks
