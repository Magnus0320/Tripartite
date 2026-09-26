"""Pins, ``data/MANIFEST.json`` and ``verify`` (ARCHITECTURE.md D5, §6).

The first tests read the committed ``data/MANIFEST.json`` and assert that the D5 zip pin in
code, the pin in the manifest and the D5 table all agree (the CI test D5 requires). The rest
run ``verify`` against synthetic files in a temporary data tree.
"""

import json
from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data import manifest

COMMITTED_MANIFEST = manifest.REPO_ROOT / "data" / "MANIFEST.json"

# ARCHITECTURE.md D5 §Database — the pin, and §6, copied by hand.
D5_TABLE = {
    "name": "sandbox_database.zip",
    "bytes": 59039278,
    "sha256": "de345b0c243cd8c85355a264c5124db5db275327d2a38fa8685c6e69fabb650b",
}
# ARCHITECTURE.md §6 and F7; sizes as the HF API reports them at that revision.
HF_PIN = {
    "repo_id": "osunlp/TravelPlanner",
    "repo_type": "dataset",
    "revision": "8736504ecfc31b7f8b7e40122873c337e83fff7c",
}
HF_SIZES = {"validation.csv": 4_833_771, "validation_ref_info.jsonl": 5_052_714}


def _committed() -> manifest.Manifest:
    return manifest.load_manifest(COMMITTED_MANIFEST)


def test_the_database_zip_pin_agrees_in_code_manifest_and_d5() -> None:
    assert manifest.DATABASE_ZIP.model_dump() == D5_TABLE
    assert _committed().database_zip.model_dump() == D5_TABLE


def test_the_committed_manifest_records_the_pinned_hf_revision() -> None:
    dataset = _committed().dataset

    pinned = (manifest.HF_REPO_ID, manifest.HF_REPO_TYPE, manifest.HF_REVISION)
    assert pinned == tuple(HF_PIN.values())
    assert (dataset.repo_id, dataset.repo_type, dataset.revision) == pinned
    assert {name: entry.bytes for name, entry in dataset.files.items()} == HF_SIZES
    assert manifest.manifest_pin_problems(_committed()) == []


def test_the_committed_manifest_holds_names_sizes_and_hashes_only() -> None:
    """§8.1: nothing but names, revisions, sizes and sha256 is ever committed under data/."""
    assert json.loads(COMMITTED_MANIFEST.read_bytes()) == _committed().model_dump(mode="json")


def test_the_committed_manifest_is_written_canonically(tmp_path: Path) -> None:
    manifest.write_manifest(_committed(), tmp_path / "MANIFEST.json")

    assert (tmp_path / "MANIFEST.json").read_bytes() == COMMITTED_MANIFEST.read_bytes()


def test_check_file(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    sha = manifest.sha256_file(path)

    assert manifest.check_file(path, 3, sha) == []
    assert manifest.check_file(path, 4, sha) == ["expected 4 bytes, found 3"]
    assert manifest.check_file(path, 3, "0" * 64) == [f"expected sha256 {'0' * 64}, found {sha}"]
    assert manifest.check_file(tmp_path / "absent", 3, sha) == ["missing"]


def _problems(checks: list[manifest.Check]) -> dict[str, tuple[str, ...]]:
    return {c.label: c.problems for c in checks if not c.ok}


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_passes_when_everything_matches(synthetic_raw: Path) -> None:
    manifest.write_manifest(synthetic.matching_manifest(synthetic_raw), manifest.manifest_path())

    checks = manifest.verify()

    assert _problems(checks) == {}
    assert len(checks) == 4  # manifest, two dataset files, zip


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_names_expected_and_actual_values(synthetic_raw: Path) -> None:
    manifest.write_manifest(synthetic.matching_manifest(synthetic_raw), manifest.manifest_path())
    csv_path = synthetic_raw / "validation.csv"
    size = csv_path.stat().st_size
    csv_path.write_bytes(csv_path.read_bytes() + b"x")
    ref_path = synthetic_raw / "validation_ref_info.jsonl"
    expected_sha = manifest.sha256_file(ref_path)
    ref_path.write_bytes(ref_path.read_bytes().replace(b"Synthville", b"Synthburgh"))

    problems = _problems(manifest.verify())

    assert problems[str(csv_path)] == (f"expected {size} bytes, found {size + 1}",)
    (ref_problem,) = problems[str(ref_path)]
    assert ref_problem.startswith(f"expected sha256 {expected_sha}, found ")
    assert len(problems) == 2


@pytest.mark.usefixtures("synthetic_raw")
def test_verify_refuses_a_zip_that_differs_from_the_pin(data_dir: Path) -> None:
    zip_path = data_dir / "downloads" / "sandbox_database.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(b"not the pinned zip")

    (problem,) = _problems(manifest.verify())[str(zip_path)]

    assert problem.startswith(f"expected {manifest.DATABASE_ZIP.bytes} bytes, found 18")
    assert "architecture question (A-013)" in problem
    assert "never a reason to update the pin" in problem


@pytest.mark.usefixtures("synthetic_raw")
def test_verify_explains_how_to_get_a_missing_zip(data_dir: Path) -> None:
    zip_path = data_dir / "downloads" / "sandbox_database.zip"

    (problem,) = _problems(manifest.verify())[str(zip_path)]

    assert "Google Drive link in the upstream TravelPlanner README" in problem


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_reports_a_missing_manifest(data_dir: Path) -> None:
    problems = _problems(manifest.verify())

    assert problems == {str(data_dir / "MANIFEST.json"): ("missing; run `tripartite data fetch`",)}


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_verify_refuses_a_manifest_that_disagrees_with_the_pins(synthetic_raw: Path) -> None:
    good = synthetic.matching_manifest(synthetic_raw)
    bad = good.model_copy(
        update={
            "dataset": good.dataset.model_copy(update={"revision": "main"}),
            "database_zip": manifest.DatabaseZip(name="database.zip", bytes=1, sha256="1" * 64),
        }
    )
    manifest.write_manifest(bad, manifest.manifest_path())

    (revision, zip_pin) = _problems(manifest.verify())[str(manifest.manifest_path())]

    assert revision == f"dataset.revision is 'main', expected '{manifest.HF_REVISION}'"
    assert zip_pin.startswith("database_zip is {'name': 'database.zip'")


def test_an_invalid_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "MANIFEST.json"
    path.write_text('{"schema_version": 1, "dataset": {}, "extra": true}')

    with pytest.raises(manifest.DataError, match="invalid"):
        manifest.load_manifest(path)
