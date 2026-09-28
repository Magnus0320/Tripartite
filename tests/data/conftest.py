"""Fixtures for the data tests (data-eval; ARCHITECTURE.md D9). Synthetic data only (§8)."""

from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data import download, manifest


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data tree in ``tmp_path``, set as ``TRIPARTITE_DATA_DIR`` (D3)."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def vendor_database(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Move ``VENDOR_DATABASE_DIR`` into ``tmp_path`` for every test not marked ``local``, so no
    test can write into the real ``vendor/travelplanner/database/``. It holds a README.md, as the
    tracked upstream one would be."""
    if request.node.get_closest_marker("local") is not None:
        return manifest.VENDOR_DATABASE_DIR
    root = tmp_path_factory.mktemp("vendor") / "travelplanner" / "database"
    root.mkdir(parents=True)
    (root / "README.md").write_text("# upstream schema description\n")
    monkeypatch.setattr(manifest, "VENDOR_DATABASE_DIR", root)
    return root


@pytest.fixture
def synthetic_raw(data_dir: Path) -> Path:
    return synthetic.write_synthetic_data_dir(data_dir) / "raw"


@pytest.fixture
def synthetic_zip_pin(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> manifest.DatabaseZip:
    """A synthetic database zip on disk, with the zip pin and the expected database files
    replaced by its own size, sha256 and contents."""
    path = synthetic.write_database_zip(data_dir / "downloads" / "sandbox_database.zip")
    pin = manifest.DatabaseZip(
        name="sandbox_database.zip",
        bytes=path.stat().st_size,
        sha256=manifest.sha256_file(path),
    )
    for module in (manifest, download):
        monkeypatch.setattr(module, "DATABASE_ZIP", pin)
        monkeypatch.setattr(module, "EXPECTED_DATABASE_FILES", synthetic.database_sizes())
    return pin
