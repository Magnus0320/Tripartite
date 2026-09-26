"""Fixtures for the data tests (data-eval; ARCHITECTURE.md D9). Synthetic data only (§8)."""

from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data import download, manifest

SYNTHETIC_ZIP_BYTES = b"PK synthetic stand-in for the sandbox database zip\n"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data tree in ``tmp_path``; every data path now resolves inside it."""
    root = tmp_path / "data"
    monkeypatch.setattr(manifest, "DATA_DIR", root)
    return root


@pytest.fixture
def synthetic_raw(data_dir: Path) -> Path:
    raw = data_dir / "raw"
    synthetic.write_raw(raw)
    return raw


@pytest.fixture
def synthetic_zip_pin(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> manifest.DatabaseZip:
    """A small stand-in zip on disk, with the zip pin replaced by its own size and sha256."""
    path = data_dir / "downloads" / "sandbox_database.zip"
    path.parent.mkdir(parents=True)
    path.write_bytes(SYNTHETIC_ZIP_BYTES)
    pin = manifest.DatabaseZip(
        name="sandbox_database.zip",
        bytes=len(SYNTHETIC_ZIP_BYTES),
        sha256=manifest.sha256_file(path),
    )
    monkeypatch.setattr(manifest, "DATABASE_ZIP", pin)
    monkeypatch.setattr(download, "DATABASE_ZIP", pin)
    return pin
