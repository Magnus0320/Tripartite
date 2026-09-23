"""Shared pytest setup (foundation; ARCHITECTURE.md D9 §Shared files, item 5).

The ``local`` marker is registered in ``pyproject.toml``. Every test that is not marked
``local`` runs in the fake modes that CI uses (D1). Each session adds its own
``conftest.py`` inside the test package it owns.
"""

import pytest

FAKE_MODE_ENV = {"TRIPARTITE_LLM": "fake", "TRIPARTITE_EVAL_BRIDGE": "fake"}


@pytest.fixture(autouse=True)
def fake_mode_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the D1 fake-mode variables for every test not marked ``local``."""
    if request.node.get_closest_marker("local") is None:
        for name, value in FAKE_MODE_ENV.items():
            monkeypatch.setenv(name, value)
