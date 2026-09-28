"""Fixtures for the data-boundary tests (model; ARCHITECTURE.md D3, D9). Synthetic data only (§8).

Tests not marked ``local`` read the shared synthetic set through ``TRIPARTITE_DATA_DIR``; nothing
in ``tripartite.data`` is patched. Local tests read the real data under ``data/``.
"""

import pytest

from tests.fixtures.synthetic_data import write_synthetic_data_dir


@pytest.fixture(autouse=True)
def synthetic_data(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.get_closest_marker("local") is None:
        root = write_synthetic_data_dir(tmp_path_factory.mktemp("data"))
        monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))
