"""Fixtures for the pipeline tests (model; ARCHITECTURE.md D3, D7, D9). Synthetic data only (§8).

Tests not marked ``local`` read a scored copy of the shared synthetic set through
``TRIPARTITE_DATA_DIR`` (``tests/fixtures/model/scored_synthetic.py``: ``level`` and
``local_constraint`` rewritten in this copy, as D3 v0.9 requires for anything that aggregates);
nothing in ``tripartite.data`` is patched. Local tests read the real data under ``data/``.

Every test, local or not, runs under the repository guard: it fails if the test changed a
committed report or anything under ``runs/`` other than ``runs/.model.lock`` and
``runs/ollama-server.log``.
"""

from collections.abc import Iterator

import pytest

from tests.fixtures.model.run_deps import RepositoryGuard
from tests.fixtures.model.scored_synthetic import write_scored_synthetic_data_dir
from tripartite.config import StackConfig, load_stack


@pytest.fixture(autouse=True)
def scored_synthetic_data(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.get_closest_marker("local") is None:
        root = write_scored_synthetic_data_dir(tmp_path_factory.mktemp("data"))
        monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))


@pytest.fixture(autouse=True)
def repository_unchanged() -> Iterator[None]:
    guard = RepositoryGuard()
    yield
    assert guard.check() == []


@pytest.fixture
def stack() -> StackConfig:
    return load_stack()
