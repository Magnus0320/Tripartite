"""The pinned tokenizer and its marker (ARCHITECTURE.md D4, S4)."""

import json
from pathlib import Path

import pytest

from tests.fixtures.model.synthetic_tokenizer import expected_user_prompt
from tripartite.config import StackConfig
from tripartite.llm.errors import TokenizerError
from tripartite.llm.tokenizer import (
    MARKER,
    Tokenizer,
    check_tokenizer_dir,
    lcp,
    load_tokenizer,
    write_marker,
)


def test_counts_and_ids(tokenizer: Tokenizer, stack: StackConfig) -> None:
    assert tokenizer.id == stack.tokenizer_id
    assert tokenizer.count("") == 0
    assert tokenizer.count("abc") == 3
    assert tokenizer.count("é") == 2  # two UTF-8 bytes
    for special in ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>"):
        assert tokenizer.count(special) == 1
    prompt = expected_user_prompt("hi ✈")
    assert tokenizer.decode(tokenizer.encode_ids(prompt)) == prompt


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([], [], 0),
        ([1, 2, 3], [1, 2, 3], 3),
        ([1, 2, 3], [1, 2], 2),
        ([1, 2], [2, 1], 0),
        ([1, 2, 3, 4], [1, 2, 9, 4], 2),
    ],
)
def test_lcp(a: list[int], b: list[int], expected: int) -> None:
    assert lcp(a, b) == expected
    assert lcp(b, a) == expected


def test_marker_records_sizes_and_hashes(tokenizer_dir: Path, stack: StackConfig) -> None:
    marker = json.loads((tokenizer_dir / MARKER).read_text(encoding="utf-8"))

    assert marker["repo"] == "Qwen/Qwen3-8B"
    assert marker["revision"] == stack.tokenizer.revision
    assert sorted(marker["files"]) == ["tokenizer.json", "tokenizer_config.json"]
    size = (tokenizer_dir / "tokenizer.json").stat().st_size
    assert marker["files"]["tokenizer.json"]["bytes"] == size


def test_missing_marker_is_refused(tokenizer_dir: Path, stack: StackConfig) -> None:
    (tokenizer_dir / MARKER).unlink()

    with pytest.raises(TokenizerError, match="make pull-model"):
        load_tokenizer(stack, tokenizer_dir)


def test_files_from_another_revision_are_refused(tokenizer_dir: Path, stack: StackConfig) -> None:
    write_marker(tokenizer_dir, "Qwen/Qwen3-8B", "f" * 40)

    with pytest.raises(TokenizerError, match=f"Qwen/Qwen3-8B@{'f' * 40}"):
        load_tokenizer(stack, tokenizer_dir)


def test_an_edited_or_missing_file_is_refused(tokenizer_dir: Path, stack: StackConfig) -> None:
    config = tokenizer_dir / "tokenizer_config.json"
    config.write_text(config.read_text(encoding="utf-8") + " ", encoding="utf-8")
    (tokenizer_dir / "tokenizer.json").unlink()

    problems = check_tokenizer_dir(tokenizer_dir, "Qwen/Qwen3-8B", stack.tokenizer.revision)

    assert len(problems) == 2
    assert "tokenizer.json is missing" in problems[0]
    assert "tokenizer_config.json differs" in problems[1]


def test_an_empty_folder_is_refused(tmp_path: Path, stack: StackConfig) -> None:
    with pytest.raises(TokenizerError, match="missing"):
        Tokenizer.from_dir(tmp_path, "Qwen/Qwen3-8B", stack.tokenizer.revision)
