"""The shared synthetic set, re-exported for data-eval's own tests (ARCHITECTURE.md D3, FU-14).

The set lives in ``tests.fixtures.synthetic_data``, which other sessions import. Only
``matching_manifest`` and the synthetic database zip are defined here, because only data-eval's
own tests need them.

``write_database_zip`` writes a small stand-in for the sandbox database zip with the pinned
zip's layout (D5 §Database — unpacking): directory entries, the 8 data files under a top-level
``database/`` folder, five ``.DS_Store`` files and ``__MACOSX/database/background/._.DS_Store``.
The data files hold ``DATABASE_FILES``, never rows of the real database (§8).
"""

import stat
import zipfile
from pathlib import Path

from tests.fixtures.synthetic_data import (
    COLUMNS,
    N,
    budget,
    canaries,
    local_constraint,
    people_number,
    query,
    ref_line,
    row,
    visiting_city_number,
    write_csv,
    write_jsonl,
    write_raw,
    write_synthetic_data_dir,
)
from tripartite.data import manifest

__all__ = [
    "COLUMNS",
    "DATABASE_FILES",
    "N",
    "budget",
    "canaries",
    "database_sizes",
    "local_constraint",
    "matching_manifest",
    "people_number",
    "query",
    "ref_line",
    "row",
    "visiting_city_number",
    "write_csv",
    "write_database_zip",
    "write_jsonl",
    "write_raw",
    "write_synthetic_data_dir",
]

DATABASE_FILES = {
    "background/citySet_with_states.txt": b"Synthville\tSynthstate\n",
    "background/citySet.txt": b"Synthville\n",
    "background/stateSet.txt": b"Synthstate\n",
    "attractions/attractions.csv": b"Name,City\nSynthetic Park,Synthville\n",
    "flights/clean_Flights_2022.csv": b"Flight Number,Price\nF0000001,100\n",
    "googleDistanceMatrix/distance.csv": b"origin,destination\nSynthville,Synthburgh\n",
    "restaurants/clean_restaurant_2022.csv": b"Name,City\nCafe Synth,Synthville\n",
    "accommodations/clean_accommodations_2022.csv": b"NAME,city\nSynth Inn,Synthville\n",
}
"""The synthetic database: path under ``vendor/travelplanner/database/`` -> bytes."""
DIRECTORIES = ("database/", *sorted({f"database/{p.split('/')[0]}/" for p in DATABASE_FILES}))
CLUTTER = {
    "database/.DS_Store": b"\0" * 16,
    **{f"database/{d}/.DS_Store": b"\0" * 8 for d in ("background", "flights", "restaurants")},
    "database/accommodations/.DS_Store": b"\0" * 8,
    "__MACOSX/database/background/._.DS_Store": b"\0" * 4,
}
"""The macOS clutter the pinned zip holds: five .DS_Store files and one AppleDouble file."""


def database_sizes() -> dict[str, int]:
    return {path: len(data) for path, data in DATABASE_FILES.items()}


def write_database_zip(
    path: Path,
    files: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
    symlinks: tuple[str, ...] = (),
) -> Path:
    """Write a zip with the pinned layout: ``files`` (default ``DATABASE_FILES``) under
    ``database/``, the directory entries and the macOS clutter, then ``extra`` entries by their
    exact names, and ``symlinks`` as symlink entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for directory in DIRECTORIES:
            archive.writestr(directory, b"")
        for name, data in (DATABASE_FILES if files is None else files).items():
            archive.writestr(f"database/{name}", data)
        for name, data in {**CLUTTER, **(extra or {})}.items():
            archive.writestr(name, data)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"../../etc/passwd")
    return path


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
