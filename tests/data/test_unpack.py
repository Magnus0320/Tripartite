"""Database unpacking (ARCHITECTURE.md D5 §Database — unpacking), on synthetic zips only (§8).

Every zip here has the pinned zip's layout (``synthetic.write_database_zip``), with the pin and
the expected files replaced by the synthetic ones. The vendored database directory is a
temporary one (the autouse ``vendor_database`` fixture), holding a stand-in upstream README.md.
"""

import contextlib
import zipfile
from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data import download, manifest


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _repin(zip_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``zip_path`` the pinned zip, so a test reaches the entry checks."""
    pin = manifest.DatabaseZip(
        name="sandbox_database.zip",
        bytes=zip_path.stat().st_size,
        sha256=manifest.sha256_file(zip_path),
    )
    for module in (manifest, download):
        monkeypatch.setattr(module, "DATABASE_ZIP", pin)
    current = manifest.load_manifest(manifest.manifest_path())
    manifest.write_manifest(
        current.model_copy(update={"database_zip": pin}), manifest.manifest_path()
    )


@pytest.fixture
def ready(synthetic_raw: Path, synthetic_zip_pin: manifest.DatabaseZip) -> Path:
    """A data tree with a manifest (no database_files yet) and the synthetic zip as the pin."""
    manifest.write_manifest(synthetic.matching_manifest(synthetic_raw), manifest.manifest_path())
    return manifest.database_zip_path()


@pytest.mark.usefixtures("ready")
def test_the_first_unpack_writes_the_eight_files_and_records_their_sha256(
    vendor_database: Path,
) -> None:
    result = download.unpack_database()

    assert (result.unpacked, result.recorded) == (True, True)
    tree = _tree(vendor_database)
    assert tree == {**synthetic.DATABASE_FILES, "README.md": b"# upstream schema description\n"}
    recorded = manifest.load_manifest(manifest.manifest_path()).database_files
    assert recorded == result.files
    assert recorded == {
        path: manifest.FileEntry(
            bytes=len(data), sha256=manifest.sha256_file(vendor_database / path)
        )
        for path, data in synthetic.DATABASE_FILES.items()
    }
    assert not (vendor_database / download.UNPACK_TMP).exists()


@pytest.mark.usefixtures("ready")
def test_a_second_unpack_is_a_no_op(vendor_database: Path) -> None:
    download.unpack_database()
    before = manifest.manifest_path().read_bytes()
    mtimes = {p: p.stat().st_mtime_ns for p in vendor_database.rglob("*") if p.is_file()}

    result = download.unpack_database()

    assert (result.unpacked, result.recorded) == (False, False)
    assert manifest.manifest_path().read_bytes() == before
    assert {p: p.stat().st_mtime_ns for p in vendor_database.rglob("*") if p.is_file()} == mtimes


@pytest.mark.usefixtures("ready")
def test_a_damaged_tree_is_restored_from_the_zip(vendor_database: Path) -> None:
    download.unpack_database()
    before = manifest.manifest_path().read_bytes()
    (vendor_database / "flights/clean_Flights_2022.csv").write_bytes(b"damaged")
    (vendor_database / "background/stateSet.txt").unlink()

    result = download.unpack_database()

    assert (result.unpacked, result.recorded) == (True, False)
    assert {p: d for p, d in _tree(vendor_database).items() if p != "README.md"} == (
        synthetic.DATABASE_FILES
    )
    assert manifest.manifest_path().read_bytes() == before


@pytest.mark.usefixtures("ready")
def test_recorded_hashes_that_the_zip_does_not_reproduce_are_refused(
    vendor_database: Path,
) -> None:
    download.unpack_database()
    mpath = manifest.manifest_path()
    current = manifest.load_manifest(mpath)
    assert current.database_files is not None
    wrong = dict(current.database_files)
    wrong["background/citySet.txt"] = wrong["background/citySet.txt"].model_copy(
        update={"sha256": "0" * 64}
    )
    manifest.write_manifest(current.model_copy(update={"database_files": wrong}), mpath)
    before_manifest = mpath.read_bytes()
    (vendor_database / "attractions/attractions.csv").write_bytes(b"damaged")

    with pytest.raises(manifest.DataError, match=r"\['background/citySet.txt'\] to other sha256"):
        download.unpack_database()

    assert mpath.read_bytes() == before_manifest
    assert (vendor_database / "attractions/attractions.csv").read_bytes() == b"damaged"
    assert not (vendor_database / download.UNPACK_TMP).exists()


def test_a_zip_that_differs_from_the_pin_is_never_opened(
    ready: Path, monkeypatch: pytest.MonkeyPatch, vendor_database: Path
) -> None:
    ready.write_bytes(ready.read_bytes() + b"tampered")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("an unverified zip was opened")

    monkeypatch.setattr(download.zipfile, "ZipFile", forbidden)

    with pytest.raises(manifest.DataError, match=r"expected .* bytes, found"):
        download.unpack_database()
    assert _tree(vendor_database) == {"README.md": b"# upstream schema description\n"}


REFUSALS = [
    ({"extra": {"/etc/passwd": b"x"}}, "absolute path, drive letter or backslash"),
    ({"extra": {"C:/database/x.txt": b"x"}}, "absolute path, drive letter or backslash"),
    ({"extra": {"database\\background\\x.txt": b"x"}}, "absolute path, drive letter or backslash"),
    ({"extra": {"database/../../outside.txt": b"x"}}, "'..' component"),
    ({"symlinks": ("database/background/link.txt",)}, "symlink"),
    ({"extra": {"other/readme.txt": b"x"}}, "outside database/ and __MACOSX/"),
    ({"extra": {"README.md": b"x"}}, "outside database/ and __MACOSX/"),
    ({"extra": {"database/background/extra.txt": b"x"}}, "unexpected ['background/extra.txt']"),
    ({"extra": {"database/README.md": b"x"}}, "unexpected ['README.md']"),
    ({"extra": {"database": b"x"}}, "unexpected ['']"),
    (
        {"files": {p: d for p, d in synthetic.DATABASE_FILES.items() if "flights" not in p}},
        "missing ['flights/clean_Flights_2022.csv']",
    ),
    (
        {"files": {**synthetic.DATABASE_FILES, "background/stateSet.txt": b"wrong size"}},
        "background/stateSet.txt is 10 bytes, expected 11",
    ),
    (
        {"extra": {"database/background/citySet.txt": b"Synthville\n"}},
        "duplicated ['background/citySet.txt']",
    ),
]


@pytest.mark.usefixtures("ready")
@pytest.mark.parametrize(("layout", "message"), REFUSALS)
def test_the_whole_zip_is_refused_and_nothing_is_written(
    layout: dict[str, object],
    message: str,
    vendor_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip_path = manifest.database_zip_path()
    duplicate = "duplicated" in message
    with (
        pytest.warns(UserWarning, match="Duplicate name") if duplicate else contextlib.nullcontext()
    ):
        synthetic.write_database_zip(zip_path, **layout)  # type: ignore[arg-type]
    _repin(zip_path, monkeypatch)
    before = manifest.manifest_path().read_bytes()

    with pytest.raises(manifest.DataError, match="refusing the database zip") as info:
        download.unpack_database()

    assert message in str(info.value)
    assert _tree(vendor_database) == {"README.md": b"# upstream schema description\n"}
    assert manifest.manifest_path().read_bytes() == before


@pytest.mark.usefixtures("synthetic_zip_pin")
def test_the_pinned_layout_maps_exactly_to_the_expected_files(tmp_path: Path) -> None:
    """Directory entries, __MACOSX/ and .DS_Store / ._* are skipped; database/ is stripped."""
    path = synthetic.write_database_zip(tmp_path / "db.zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        members = download.plan_database_members(archive)

    assert "__MACOSX/database/background/._.DS_Store" in names
    assert sum(n.endswith(".DS_Store") for n in names) == 6  # five plus the AppleDouble one
    assert sorted(members) == sorted(manifest.EXPECTED_DATABASE_FILES)
    assert {p: info.filename for p, info in members.items()} == {
        p: f"database/{p}" for p in manifest.EXPECTED_DATABASE_FILES
    }
