"""Fixtures for the API tests (api; ARCHITECTURE.md D3 §Planner inputs in other sessions' tests).

Every test here reads the shared synthetic data set through ``TRIPARTITE_DATA_DIR``, set with
``monkeypatch.setenv``. Nothing in ``tripartite.data`` is patched, and the real data is never
read (§8).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.synthetic_data import write_synthetic_data_dir
from tripartite.api.app import app


@pytest.fixture(autouse=True)
def synthetic_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = write_synthetic_data_dir(tmp_path / "data")
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))
    return root


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The app, started (lifespan included) on the synthetic data."""
    with TestClient(app) as client:
        yield client
