"""Vendor integrity check (ARCHITECTURE.md D1, D5, D9 §Shared files, item 4). Owner: data-eval.

CI runs this as a step guarded by ``vendor/travelplanner/VENDOR.lock``. It checks only the
**git-tracked** files, ``git ls-files -z -- vendor/travelplanner``, and never walks the file
system, so the unpacked sandbox database (untracked and gitignored) is outside it; that is
checked by ``tripartite data verify`` instead. It fails unless:

1. ``VENDOR.lock`` is valid and names the pinned upstream repository and commit;
2. every tracked file under ``vendor/travelplanner/`` other than ``VENDOR.lock`` and
   ``VENDOR.md`` is a regular file listed in the lock, with the same size, sha256 and git
   blob id;
3. every lock entry is tracked and present;
4. every lock path lies inside D5's vendored path list;
5. no lock path, and no tracked file anywhere under ``vendor/``, matches ``*ref_info*`` or
   ``*.csv`` (case-insensitive, like §8).

Standard library only. Run from anywhere inside the repository:

    uv run python scripts/vendor_check.py
"""

import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

VENDOR_DIR = "vendor/travelplanner"
LOCK_NAME = "VENDOR.lock"
LOCAL_FILES = frozenset({LOCK_NAME, "VENDOR.md"})
"""Written by this project, not upstream, so not in the lock."""
UPSTREAM_REPO = "https://github.com/OSU-NLP-Group/TravelPlanner"
UPSTREAM_COMMIT = "e52c87f4ac348a3410c46dc3553c519db5ec5e23"
"""The §6 pin. Changing it is an architecture decision."""
D5_DIRECTORIES = ("evaluation/", "tools/", "utils/")
D5_FILES = frozenset(
    {
        "agents/prompts.py",
        "postprocess/example_evaluation.jsonl",
        "database/README.md",
        "LICENSE",
        "README.md",
    }
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_BLOB = re.compile(r"^[0-9a-f]{40}$")


def _git(root: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout.decode()
    return [p for p in out.split("\0") if p]


def forbidden_name(path: str) -> bool:
    """A reference-information or CSV path, which is never vendored (D5, §8)."""
    lower = path.lower()
    return fnmatch.fnmatchcase(lower, "*ref_info*") or lower.endswith(".csv")


def in_d5_list(path: str) -> bool:
    return path in D5_FILES or path.startswith(D5_DIRECTORIES)


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def lock_problems(lock: Any) -> list[str]:
    """What is wrong with the structure of a parsed lock; empty if nothing."""
    if not isinstance(lock, dict) or set(lock) != {"schema_version", "upstream", "files"}:
        return ["must be an object with exactly schema_version, upstream and files"]
    problems = []
    if lock["schema_version"] != 1:
        problems.append(f"schema_version is {lock['schema_version']!r}, expected 1")
    if lock["upstream"] != {"repo": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT}:
        problems.append(
            f"upstream is {lock['upstream']!r}, expected repo {UPSTREAM_REPO} "
            f"at commit {UPSTREAM_COMMIT}"
        )
    files = lock["files"]
    if not isinstance(files, dict) or not files:
        return [*problems, "files must be a non-empty object"]
    for path, entry in files.items():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"bytes", "sha256", "git_blob"}
            or type(entry["bytes"]) is not int
            or not isinstance(entry["sha256"], str)
            or not SHA256.match(entry["sha256"])
            or not isinstance(entry["git_blob"], str)
            or not GIT_BLOB.match(entry["git_blob"])
        ):
            problems.append(f"{path}: entry must be {{bytes, sha256, git_blob}}, got {entry!r}")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or str(pure) != path:
            problems.append(f"{path}: not a normalized relative path")
        elif path in LOCAL_FILES:
            problems.append(f"{path}: a local file, not an upstream one")
        elif not in_d5_list(path):
            problems.append(f"{path}: outside D5's vendored path list")
        if forbidden_name(path):
            problems.append(f"{path}: a *ref_info* or *.csv path is never vendored (D5)")
    return problems


def file_problems(file: Path, entry: dict[str, Any]) -> list[str]:
    if file.is_symlink() or not file.is_file():
        return ["not a regular file"]
    data = file.read_bytes()
    problems = []
    if len(data) != entry["bytes"]:
        problems.append(f"expected {entry['bytes']} bytes, found {len(data)}")
    sha256 = hashlib.sha256(data).hexdigest()
    if sha256 != entry["sha256"]:
        problems.append(f"expected sha256 {entry['sha256']}, found {sha256}")
    blob = git_blob_id(data)
    if blob != entry["git_blob"]:
        problems.append(f"expected git blob {entry['git_blob']}, found {blob}")
    return problems


def check(root: Path) -> tuple[list[str], int]:
    """Every problem found, and the number of lock entries that matched."""
    vendor = root / VENDOR_DIR
    try:
        lock = json.loads((vendor / LOCK_NAME).read_bytes())
    except (OSError, ValueError) as exc:
        return [f"{VENDOR_DIR}/{LOCK_NAME}: cannot read: {exc}"], 0
    problems = [f"{VENDOR_DIR}/{LOCK_NAME}: {p}" for p in lock_problems(lock)]
    if problems:
        return problems, 0
    files: dict[str, dict[str, Any]] = lock["files"]

    prefix = VENDOR_DIR + "/"
    tracked = {p.removeprefix(prefix) for p in _git(root, "ls-files", "-z", "--", VENDOR_DIR)}
    matched = 0
    for path in sorted(tracked - LOCAL_FILES):
        entry = files.get(path)
        if entry is None:
            problems.append(f"{prefix}{path}: tracked but not in {LOCK_NAME}")
            continue
        found = file_problems(vendor / path, entry)
        problems.extend(f"{prefix}{path}: {p}" for p in found)
        matched += not found
    problems.extend(
        f"{prefix}{path}: in {LOCK_NAME} but not tracked by git"
        for path in sorted(set(files) - tracked)
    )
    problems.extend(
        f"{path}: a *ref_info* or *.csv file is committed under vendor/ (D5, §8)"
        for path in _git(root, "ls-files", "-z", "--", "vendor")
        if forbidden_name(path)
    )
    return problems, matched


def main() -> int:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    problems, matched = check(root)
    if problems:
        print("vendor check: FAILED (ARCHITECTURE.md D5, D9)")
        for line in problems:
            print(f"  {line}")
        return 1
    print(f"vendor check: OK ({matched} tracked files match {LOCK_NAME} at {UPSTREAM_COMMIT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
