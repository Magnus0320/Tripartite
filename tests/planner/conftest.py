"""Fixtures for the planner tests (model; ARCHITECTURE.md D3, D9). Synthetic data only (§8).

Tests not marked ``local`` read the shared synthetic set through ``TRIPARTITE_DATA_DIR``; nothing
in ``tripartite.data`` is patched.
"""

from pathlib import Path

import pytest

from tests.fixtures.model.synthetic_tokenizer import write_synthetic_tokenizer_dir
from tests.fixtures.synthetic_data import write_synthetic_data_dir
from tripartite.config import load_stack
from tripartite.llm.chat_template import ChatTemplate, load_chat_template


@pytest.fixture(autouse=True)
def synthetic_data(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.get_closest_marker("local") is None:
        root = write_synthetic_data_dir(tmp_path_factory.mktemp("data"))
        monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(root))


@pytest.fixture
def chat(tmp_path: Path) -> ChatTemplate:
    stack = load_stack()
    directory = write_synthetic_tokenizer_dir(tmp_path / "tokenizer", stack.tokenizer.revision)
    return load_chat_template(stack, directory)
