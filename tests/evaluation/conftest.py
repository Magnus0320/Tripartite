"""Fixtures for the evaluation tests (data-eval; ARCHITECTURE.md D9). Synthetic data only (§8)."""

from pathlib import Path

import pytest

from tests.data import synthetic


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty data tree in ``tmp_path``, set as ``TRIPARTITE_DATA_DIR`` (D3)."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))
    return root


@pytest.fixture
def synthetic_raw(data_dir: Path) -> Path:
    return synthetic.write_synthetic_data_dir(data_dir) / "raw"
