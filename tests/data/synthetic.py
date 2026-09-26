"""The shared synthetic set, re-exported for data-eval's own tests (ARCHITECTURE.md D3, FU-14).

The set lives in ``tests.fixtures.synthetic_data``, which other sessions import. Only
``matching_manifest`` is defined here, because only data-eval's manifest tests need it.
"""

from pathlib import Path

from tests.fixtures.synthetic_data import (
    COLUMNS,
    LOCAL_CONSTRAINTS,
    N,
    budget,
    canaries,
    query,
    ref_line,
    row,
    write_csv,
    write_jsonl,
    write_raw,
    write_synthetic_data_dir,
)
from tripartite.data import manifest

__all__ = [
    "COLUMNS",
    "LOCAL_CONSTRAINTS",
    "N",
    "budget",
    "canaries",
    "matching_manifest",
    "query",
    "ref_line",
    "row",
    "write_csv",
    "write_jsonl",
    "write_raw",
    "write_synthetic_data_dir",
]


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
