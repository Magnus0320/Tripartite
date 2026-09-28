"""The fake LLM client (``TRIPARTITE_LLM=fake``; ARCHITECTURE.md D1, D3, D4)."""

import pytest

from tests.fixtures.model.synthetic_tokenizer import expected_user_prompt
from tripartite.config import StackConfig
from tripartite.llm.calibration import post_check
from tripartite.llm.fake_client import FAKE_OUTPUT, FakeClient, make_client
from tripartite.llm.ollama_client import (
    GenerateOptions,
    GenerateRequest,
    OllamaClient,
    build_generate_body,
)
from tripartite.llm.tokenizer import Tokenizer


def request(prompt: str, num_predict: int = 4096) -> GenerateRequest:
    options = GenerateOptions(32768, num_predict, 0.7, 0.8, 20, 0.0, 1.0, 0, ("<|im_end|>",))
    return GenerateRequest("qwen3:8b-q4_K_M", prompt, options)


def test_records_every_body_byte_for_byte(tokenizer: Tokenizer) -> None:
    fake = FakeClient(tokenizer)
    first, second = request(expected_user_prompt("a ü")), request(expected_user_prompt("b"))

    fake.generate(first)
    fake.generate(second)

    assert fake.requests == [build_generate_body(first), build_generate_body(second)]


def test_reports_the_local_count_so_mode_total_passes(tokenizer: Tokenizer) -> None:
    prompt = expected_user_prompt("Query: a trip")

    result = FakeClient(tokenizer).generate(request(prompt))

    assert result.prompt_eval_count == tokenizer.count(prompt)
    assert result.text == FAKE_OUTPUT
    assert result.done_reason == "stop"
    assert result.eval_count == tokenizer.count(FAKE_OUTPUT)
    check = post_check(
        "total",
        prompt_tokens=tokenizer.count(prompt),
        lcp=0,
        prompt_eval_count=result.prompt_eval_count,
        prompt_eval_cached_count=None,
    )
    assert check.ok


def test_output_is_cut_at_num_predict(tokenizer: Tokenizer) -> None:
    fake = FakeClient(tokenizer, respond=lambda _r: "OKAY")

    result = fake.generate(request("x", num_predict=2))

    assert (result.text, result.eval_count, result.done_reason) == ("OK", 2, "length")


def test_make_client_follows_the_environment(
    stack: StackConfig, tokenizer: Tokenizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(make_client(stack, tokenizer), FakeClient)  # the CI default
    monkeypatch.delenv("TRIPARTITE_LLM")
    client = make_client(stack, tokenizer)
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://127.0.0.1:11435"
