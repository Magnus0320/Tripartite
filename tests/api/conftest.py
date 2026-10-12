"""Fixtures for the API tests (api; ARCHITECTURE.md D3 §Planner inputs in other sessions' tests).

Every test here reads a synthetic data set through ``TRIPARTITE_DATA_DIR``, set with
``monkeypatch.setenv``. Nothing in ``tripartite.data`` is patched, and the real data is never
read (§8). The set is the shared one's scoreable copy (``scoreable=True``, FU-32), because a run
scores its plans with ``aggregate()``, which needs a real level (D3, v0.9).

Runs go to a temporary ``runs/`` (``app.state.settings``), never to the repository's, and two
guards hold for every test: nothing connects to an Ollama port, and the repository's ``runs/``
is left as it was.
"""

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import synthetic_data as shared_set
from tripartite.api.app import app
from tripartite.api.jobs import ApiSettings
from tripartite.config import RUNS_DIR

OLLAMA_PORTS = {11434, 11435}
"""The desktop app and the dedicated server: no test here may contact either."""


@pytest.fixture(autouse=True)
def synthetic_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = shared_set.write_synthetic_data_dir(tmp_path / "data", scoreable=True)
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ApiSettings:
    """The app's settings for this test: a temporary ``runs/`` and a fast stage poll."""
    settings = ApiSettings(runs_dir=tmp_path / "runs", sse_poll_s=0.005)
    monkeypatch.setattr(app.state, "settings", settings)
    return settings


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and len(address) >= 2 and address[1] in OLLAMA_PORTS:
            raise AssertionError(f"a test tried to connect to {address}")
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def _repo_runs() -> list[str]:
    return sorted(str(path) for path in RUNS_DIR.rglob("*")) if RUNS_DIR.exists() else []


@pytest.fixture(autouse=True)
def repo_runs_untouched() -> Iterator[None]:
    before = _repo_runs()
    yield
    assert _repo_runs() == before


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The app, started (lifespan included) on the synthetic data."""
    with TestClient(app) as client:
        yield client
