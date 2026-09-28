"""Fixtures for the model-layer tests (model; ARCHITECTURE.md D3, D9). Synthetic data only (§8).

Every test not marked ``local`` reads the shared synthetic data set through
``TRIPARTITE_DATA_DIR`` (D3 §Planner inputs in other sessions' tests); nothing in
``tripartite.data`` is patched. Local tests read the real data under ``data/``.
"""

from pathlib import Path

import pytest

from tests.fixtures.model.synthetic_tokenizer import write_synthetic_tokenizer_dir
from tests.fixtures.synthetic_data import write_synthetic_data_dir
from tripartite.config import StackConfig, load_stack
from tripartite.llm.chat_template import ChatTemplate, load_chat_template
from tripartite.llm.tokenizer import Tokenizer, load_tokenizer


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
def stack() -> StackConfig:
    return load_stack()


@pytest.fixture
def tokenizer_dir(tmp_path: Path, stack: StackConfig) -> Path:
    return write_synthetic_tokenizer_dir(tmp_path / "tokenizer", stack.tokenizer.revision)


@pytest.fixture
def tokenizer(stack: StackConfig, tokenizer_dir: Path) -> Tokenizer:
    return load_tokenizer(stack, tokenizer_dir)


@pytest.fixture
def chat(stack: StackConfig, tokenizer_dir: Path) -> ChatTemplate:
    return load_chat_template(stack, tokenizer_dir)
