"""Whether the real evaluator can run, cheaply (ARCHITECTURE.md D8 §health, FU-18).

``evaluator_ready()`` is ``/api/health``'s ``evaluator_ready`` flag. It is cheap by construction:
it calls ``os.stat`` and reads ``MANIFEST.json`` (a few kB), and nothing else. It never hashes a
file and never starts a subprocess; full verification stays in ``tripartite data verify``
(``make doctor``).

With ``TRIPARTITE_EVAL_BRIDGE=fake`` it is ``True`` without touching the file system. With the
variable unset or ``real``, it is ``True`` exactly when:

- ``vendor/travelplanner/VENDOR.lock`` exists;
- the evalenv interpreter ``evalenv/.venv/bin/python`` exists (``make setup``);
- ``MANIFEST.json`` under the data root (``TRIPARTITE_DATA_DIR``, else ``<repo>/data``) loads and
  has ``database_files`` recorded;
- each of the 8 database files (``EXPECTED_DATABASE_FILES``) exists under
  ``vendor/travelplanner/database/`` with exactly the byte size recorded for it; and
- ``raw/validation.csv`` exists with the byte size recorded for it.

Any other value of ``TRIPARTITE_EVAL_BRIDGE`` gives ``False``, because ``bridge_from_env`` would
refuse it. It never raises: the flag must never turn the health endpoint into an error (D8).
"""

import os
import stat
from pathlib import Path
from typing import Final

from tripartite.data import manifest
from tripartite.evaluation.bridge_client import BRIDGE_ENV, EVALENV_DIR, VENDOR_DIR

VENDOR_LOCK: Final = VENDOR_DIR / "VENDOR.lock"
EVALENV_PYTHON: Final = EVALENV_DIR / ".venv" / "bin" / "python"


def _is_file(path: Path, size: int | None = None) -> bool:
    """``path`` is a regular file, after symlinks, of ``size`` bytes if given. ``os.stat`` only."""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode) and (size is None or st.st_size == size)


def evaluator_ready() -> bool:
    """Whether the evaluator has what it reads, by file sizes alone (D8)."""
    mode = os.environ.get(BRIDGE_ENV, "real")
    if mode == "fake":
        return True
    if mode != "real":
        return False
    if not (_is_file(VENDOR_LOCK) and _is_file(EVALENV_PYTHON)):
        return False
    try:
        recorded = manifest.load_manifest(manifest.manifest_path())
        csv_entry = recorded.dataset.files.get(manifest.VALIDATION_CSV)
        if recorded.database_files is None or csv_entry is None:
            return False
        database = manifest.vendor_database_dir()
        for path in manifest.EXPECTED_DATABASE_FILES:
            entry = recorded.database_files.get(path)
            if entry is None or not _is_file(database / path, entry.bytes):
                return False
        return _is_file(manifest.raw_dir() / manifest.VALIDATION_CSV, csv_entry.bytes)
    except (manifest.DataError, OSError, ValueError):
        return False
