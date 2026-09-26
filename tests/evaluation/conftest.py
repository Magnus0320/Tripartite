"""Fixtures for the evaluation tests (data-eval; ARCHITECTURE.md D9). Synthetic data only (§8)."""

from pathlib import Path

import pytest

from tests.data import synthetic
from tripartite.data import manifest


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
