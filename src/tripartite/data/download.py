"""Fetch the pinned data: the two dataset files, and the unpacked database (ARCHITECTURE.md D3,
D5, §6).

Each file is fetched by explicit name with ``huggingface_hub.hf_hub_download`` into
``data/raw/``. Nothing else in the dataset repository is ever fetched, and neither
``snapshot_download`` nor ``datasets.load_dataset`` is used (D3). A name outside the allowlist
is refused before any network access.

The first fetch records each file's size and sha256 in ``data/MANIFEST.json``. The pinned
revision is an immutable commit, so this is not a second trust decision. Later fetches must
reproduce those values exactly, or they fail and leave the manifest untouched.

**The sandbox database** (D5 §Database — unpacking). The zip is downloaded by hand and checked
against the D5 pin; ``unpack_database`` then extracts it, in Python with ``zipfile``, into
``vendor/travelplanner/database/``:

1. Nothing is read from a zip that does not match the pin.
2. Every entry is inspected before anything is written. The whole zip is refused if any entry
   has an absolute path, a drive letter, a backslash or a ``..`` component, is a symlink, or has
   a first component other than ``database`` or ``__MACOSX``.
3. Directory entries, everything under ``__MACOSX/``, ``.DS_Store`` and ``._*`` are skipped.
4. ``database/<rest>`` maps to ``vendor/travelplanner/database/<rest>``.
5. The mapped set must be exactly ``EXPECTED_DATABASE_FILES``, with those sizes in the zip.
6. The files are streamed into ``.unpack-tmp/``, sizes checked again as written and hashed,
   compared with the sha256 recorded in the manifest (or recorded there on the first unpack),
   and only then moved into place. ``.unpack-tmp/`` is always removed, and the tracked
   ``README.md`` next to it is never touched.
7. A tree that already matches the recorded sha256 is left alone.
"""

import hashlib
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from huggingface_hub import hf_hub_download

from tripartite.data.manifest import (
    DATABASE_ZIP,
    EXPECTED_DATABASE_FILES,
    HF_FILES,
    HF_REPO_ID,
    HF_REPO_TYPE,
    HF_REVISION,
    SCHEMA_VERSION,
    DataError,
    Dataset,
    FileEntry,
    Manifest,
    check_database_zip,
    check_file,
    database_zip_path,
    display,
    load_manifest,
    manifest_path,
    manifest_pin_problems,
    raw_dir,
    sha256_file,
    vendor_database_dir,
    write_manifest,
)
from tripartite.data.planner_inputs import TestSplitForbiddenError


def fetch_dataset_file(filename: str) -> Path:
    """Download one allowlisted file into ``data/raw/`` and return its path."""
    if "test" in filename.lower():
        raise TestSplitForbiddenError(f"refusing to download {filename!r}: test split (D3)")
    if filename not in HF_FILES:
        raise ValueError(f"refusing to download {filename!r}: not in the allowlist {HF_FILES}")
    target = raw_dir() / filename
    path = Path(
        hf_hub_download(
            repo_id=HF_REPO_ID,
            repo_type=HF_REPO_TYPE,
            revision=HF_REVISION,
            filename=filename,
            local_dir=raw_dir(),
        )
    )
    if path.resolve() != target.resolve():
        raise DataError(f"hf_hub_download wrote {path}, expected {display(target)}")
    return target


@dataclass(frozen=True)
class FetchResult:
    files: dict[str, FileEntry]
    recorded: bool
    """True if this fetch created the manifest; False if the files matched an existing one."""


def fetch() -> FetchResult:
    """Download every allowlisted file, then record it in the manifest or check it against it."""
    files = {}
    for name in HF_FILES:
        path = fetch_dataset_file(name)
        files[name] = FileEntry(bytes=path.stat().st_size, sha256=sha256_file(path))

    mpath = manifest_path()
    if not mpath.exists():
        dataset = Dataset(
            repo_id=HF_REPO_ID, repo_type=HF_REPO_TYPE, revision=HF_REVISION, files=files
        )
        write_manifest(
            Manifest(schema_version=SCHEMA_VERSION, dataset=dataset, database_zip=DATABASE_ZIP),
            mpath,
        )
        return FetchResult(files=files, recorded=True)

    manifest = load_manifest(mpath)
    problems = manifest_pin_problems(manifest)
    for name, entry in files.items():
        recorded = manifest.dataset.files.get(name)
        if recorded is not None and recorded != entry:
            problems.append(
                f"{name}: downloaded {entry.bytes} bytes with sha256 {entry.sha256}, but "
                f"{display(mpath)} has {recorded.bytes} bytes with sha256 {recorded.sha256}"
            )
    if problems:
        raise DataError("; ".join(problems))
    return FetchResult(files=files, recorded=False)


UNPACK_TMP = ".unpack-tmp"
_CHUNK = 1 << 20


def plan_database_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """The zip entries to extract, by path under the database directory (D5 steps 2 to 5).

    Raises ``DataError`` for the whole zip if any entry is unsafe or unexpected, or if the
    remaining set differs from ``EXPECTED_DATABASE_FILES``. Nothing is read or written.
    """
    refused = []
    members: dict[str, zipfile.ZipInfo] = {}
    duplicates = []
    for info in archive.infolist():
        name = info.filename
        parts = PurePosixPath(name).parts
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or "\\" in name:
            refused.append(f"{name!r}: absolute path, drive letter or backslash")
        elif ".." in parts:
            refused.append(f"{name!r}: '..' component")
        elif stat.S_ISLNK(info.external_attr >> 16):
            refused.append(f"{name!r}: symlink")
        elif not parts or parts[0] not in {"database", "__MACOSX"}:
            refused.append(f"{name!r}: outside database/ and __MACOSX/")
        elif not (
            info.is_dir()
            or parts[0] == "__MACOSX"
            or parts[-1] == ".DS_Store"
            or parts[-1].startswith("._")
        ):
            path = PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else ""
            if path in members:
                duplicates.append(path)
            members[path] = info
    if refused:
        raise DataError(f"refusing the database zip: unsafe entries {refused}")
    expected = set(EXPECTED_DATABASE_FILES)
    problems = []
    if missing := sorted(expected - set(members)):
        problems.append(f"missing {missing}")
    if extra := sorted(set(members) - expected):
        problems.append(f"unexpected {extra}")
    if duplicates:
        problems.append(f"duplicated {sorted(duplicates)}")
    problems.extend(
        f"{path} is {info.file_size} bytes, expected {EXPECTED_DATABASE_FILES[path]}"
        for path, info in sorted(members.items())
        if path in expected and info.file_size != EXPECTED_DATABASE_FILES[path]
    )
    if problems:
        raise DataError(f"refusing the database zip: {'; '.join(problems)}")
    return members


def _extract(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, size: int) -> str:
    """Stream one member to ``target``, refusing any size but ``size``; return its sha256."""
    digest = hashlib.sha256()
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, target.open("wb") as out:
        while chunk := source.read(_CHUNK):
            written += len(chunk)
            if written > size:
                break
            digest.update(chunk)
            out.write(chunk)
    if written != size:
        raise DataError(f"{info.filename}: wrote {written} bytes, expected {size}")
    return digest.hexdigest()


def _tree_matches(recorded: dict[str, FileEntry]) -> bool:
    return all(
        not check_file(vendor_database_dir() / path, size, recorded[path].sha256)
        for path, size in EXPECTED_DATABASE_FILES.items()
    )


@dataclass(frozen=True)
class UnpackResult:
    files: dict[str, FileEntry]
    unpacked: bool
    """False if the tree already matched the recorded sha256 and nothing was written."""
    recorded: bool
    """True if this unpack recorded the sha256 in the manifest for the first time."""


def unpack_database() -> UnpackResult:
    """Unpack the pinned zip into ``vendor/travelplanner/database/`` (D5 §Database — unpacking)."""
    zip_path = database_zip_path()
    if problems := check_database_zip():
        raise DataError(f"{display(zip_path)}: {'; '.join(problems)}")
    mpath = manifest_path()
    manifest = load_manifest(mpath)
    if problems := manifest_pin_problems(manifest):
        raise DataError("; ".join(problems))
    recorded = manifest.database_files
    if recorded is not None and _tree_matches(recorded):
        return UnpackResult(files=recorded, unpacked=False, recorded=False)

    root = vendor_database_dir()
    tmp = root / UNPACK_TMP
    with zipfile.ZipFile(zip_path) as archive:
        members = plan_database_members(archive)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            files = {
                path: FileEntry(
                    bytes=EXPECTED_DATABASE_FILES[path],
                    sha256=_extract(archive, info, tmp / path, EXPECTED_DATABASE_FILES[path]),
                )
                for path, info in sorted(members.items())
            }
            if recorded is not None and files != recorded:
                changed = sorted(p for p in files if files[p] != recorded.get(p))
                raise DataError(
                    f"the pinned zip unpacks {changed} to other sha256 than {display(mpath)} "
                    "records; this is an architecture question (A-013), never a reason to "
                    "update the manifest"
                )
            for path in files:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp / path, root / path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if recorded is None:
        write_manifest(manifest.model_copy(update={"database_files": files}), mpath)
    return UnpackResult(files=files, unpacked=True, recorded=recorded is None)
