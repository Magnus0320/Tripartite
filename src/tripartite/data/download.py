"""Download the two allowlisted dataset files at the pinned revision (ARCHITECTURE.md D3, §6).

Each file is fetched by explicit name with ``huggingface_hub.hf_hub_download`` into
``data/raw/``. Nothing else in the dataset repository is ever fetched, and neither
``snapshot_download`` nor ``datasets.load_dataset`` is used (D3). A name outside the allowlist
is refused before any network access.

The first fetch records each file's size and sha256 in ``data/MANIFEST.json``. The pinned
revision is an immutable commit, so this is not a second trust decision. Later fetches must
reproduce those values exactly, or they fail and leave the manifest untouched.
"""

from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

from tripartite.data.manifest import (
    DATABASE_ZIP,
    HF_FILES,
    HF_REPO_ID,
    HF_REPO_TYPE,
    HF_REVISION,
    SCHEMA_VERSION,
    DataError,
    Dataset,
    FileEntry,
    Manifest,
    display,
    load_manifest,
    manifest_path,
    manifest_pin_problems,
    raw_dir,
    sha256_file,
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
