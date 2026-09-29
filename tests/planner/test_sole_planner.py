"""The sole planner (ARCHITECTURE.md D4, D6, D3): warm-up, pre-flight, retries, post-check.

The retry tests go through the real ``OllamaClient`` over ``httpx.MockTransport``, so they cover
the model layer's mapping of each failure too. D6's retriable failures (connection refused,
HTTP 5xx, the timeout) all surface as ``TransportError`` and are retried with the same seed; every
other failure is a ``ServerError`` and is not retried.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.model.fake_ollama import FakeOllama
from tripartite.config import Generation, StackConfig, load_run_config, load_stack
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs
from tripartite.llm.calibration import Mode
from tripartite.llm.chat_template import ChatTemplate, template_from_env
from tripartite.llm.errors import (
    ContextOverflowError,
    ServerError,
    TokenizerMismatchError,
    TransportError,
    TruncationError,
)
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import LLMClient, OllamaClient, build_generate_body
from tripartite.llm.tokenizer import Tokenizer, lcp
from tripartite.planner.prompt import PromptRenderer, load_template
from tripartite.planner.sole_planner import (
    AGENT_ID,
    RETRY_PAUSE_S,
    WARMUP_SEED,
    CallRecord,
    SolePlanner,
)

URL = "http://127.0.0.1:11435"


def make_planner(
    client: LLMClient,
    *,
    tokenizer: Tokenizer | None = None,
    chat: ChatTemplate | None = None,
    mode: Mode = "total",
    sleeps: list[float] | None = None,
    **generation: Any,
) -> SolePlanner:
    run = load_run_config()
    stack = load_stack()
    renderer = PromptRenderer(
        load_template(run.prompt_path, run.prompt.sha256), chat or template_from_env(stack)
    )
    return SolePlanner(
        client=client,
        tokenizer=tokenizer or FakeTokenizer(),
        renderer=renderer,
        stack=stack,
        generation=run.generation.model_copy(update=generation),
        post_check_mode=mode,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )


def first_input() -> PlannerInput:
    return load_planner_inputs()[0]


class Recorder:
    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    def __call__(self, call: CallRecord) -> None:
        self.calls.append(call)


# --- warm-up -----------------------------------------------------------------------------------


def test_the_warm_up_is_d4s(stack: StackConfig) -> None:
    client = FakeClient(FakeTokenizer())
    planner = make_planner(client)
    calls = Recorder()

    first = planner.warm_up(calls)
    second = planner.warm_up(calls)

    assert calls.calls == [first, second]
    text = first.prompt.text
    body = text.removeprefix("<|im_start|>user\n").removesuffix(
        "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )
    assert body.startswith("Reply with OK. nonce=")
    nonce = body.removeprefix("Reply with OK. nonce=")
    assert len(nonce) == 32
    assert int(nonce, 16) >= 0
    assert second.prompt.text != text  # a fresh nonce each time
    assert (first.role, first.query_id, first.seed) == ("warmup", None, None)
    assert first.request.options.num_predict == 1
    assert first.request.options.seed == WARMUP_SEED
    assert first.post_check is not None
    assert first.post_check.ok


def test_the_first_measured_call_takes_its_lcp_against_the_warm_up() -> None:
    planner = make_planner(FakeClient(FakeTokenizer()))
    calls = Recorder()
    warmup = planner.warm_up(calls)
    inp = first_input()

    output = planner.plan(inp, 0, calls)

    tk = FakeTokenizer()
    expected = lcp(tk.encode_ids(warmup.prompt.text), tk.encode_ids(output.final.prompt.text))
    assert output.final.post_check is not None
    assert output.final.post_check.lcp == expected == len("<|im_start|>user\n")
    again = planner.plan(inp, 1, calls)
    assert again.final.post_check is not None
    assert again.final.post_check.lcp == again.final.prompt_tokens  # the same prompt was last


# --- one call ----------------------------------------------------------------------------------


def test_a_plan_call_sends_every_option_explicitly(stack: StackConfig) -> None:
    client = FakeClient(FakeTokenizer())
    planner = make_planner(client)
    calls = Recorder()

    output = planner.plan(first_input(), 2, calls)

    assert calls.calls == list(output.calls)
    assert output.text is not None
    assert len(client.requests) == 1
    body = json.loads(client.requests[0])
    assert body == json.loads(build_generate_body(output.final.request))
    assert (body["raw"], body["stream"], body["think"]) == (True, False, False)
    assert body["keep_alive"] == -1
    assert body["options"] == {
        "num_ctx": 32768,
        "num_predict": 4096,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
        "seed": 2,
        "stop": ["<|im_end|>", "<|endoftext|>"],
    }
    call = output.final
    assert (call.role, call.query_id, call.seed, call.attempt) == ("planner", "val-001", 2, 0)
    assert call.prompt_tokens == len(call.prompt.text.encode("utf-8"))
    assert AGENT_ID == "planner"


def test_the_planner_takes_only_a_planner_input() -> None:
    planner = make_planner(FakeClient(FakeTokenizer()))
    lookalike = type(
        "Lookalike", (), {"query_id": "val-001", "query": "q", "reference_information": "r"}
    )()

    with pytest.raises(TypeError, match="takes a PlannerInput"):
        planner.plan(lookalike, 0, Recorder())


def test_preflight_refuses_before_anything_is_sent() -> None:
    client = FakeClient(FakeTokenizer())
    planner = make_planner(client, num_predict=32000)  # prompt + 32000 > 32768
    calls = Recorder()

    with pytest.raises(ContextOverflowError, match="num_predict 32000 > num_ctx 32768"):
        planner.plan(first_input(), 0, calls)
    assert client.requests == []
    assert calls.calls == []


@pytest.mark.parametrize(("offset", "error"), [(-1, TruncationError), (1, TokenizerMismatchError)])
def test_a_failed_post_check_is_logged_then_raised(
    offset: int, error: type[Exception], stack: StackConfig
) -> None:
    tokenizer = FakeTokenizer()
    server = FakeOllama.for_stack(stack, tokenizer, mode="total", token_offset=offset)
    planner = make_planner(server.client(), tokenizer=tokenizer)
    calls = Recorder()

    with pytest.raises(error):
        planner.plan(first_input(), 0, calls)
    assert len(calls.calls) == 1
    check = calls.calls[0].post_check
    assert check is not None
    assert not check.ok
    assert check.observed == calls.calls[0].prompt_tokens + offset


# --- retries (D6; amendment 1: 5xx, refused and timeout are all retriable) -----------------------


def generate_reply(prompt: str) -> dict[str, Any]:
    return {
        "response": "Day 1:\nLunch: Cafe One, Synthville",
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": len(prompt.encode("utf-8")),
        "eval_count": 5,
        "load_duration": 1_000,
        "prompt_eval_duration": 2_000_000,
        "eval_duration": 3_000_000,
        "total_duration": 5_001_000,
    }


def scripted_client(failures: list[Callable[[httpx.Request], httpx.Response]]) -> OllamaClient:
    """Each generate request uses the next failure, then succeeds."""
    pending = list(failures)

    def handler(request: httpx.Request) -> httpx.Response:
        if pending:
            return pending.pop(0)(request)
        return httpx.Response(200, json=generate_reply(json.loads(request.read())["prompt"]))

    return OllamaClient(URL, transport=httpx.MockTransport(handler))


def http_503(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"error": "server busy"})


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def timed_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


RETRIABLE = {"http_5xx": http_503, "connection_refused": refused, "timeout": timed_out}


@pytest.mark.parametrize("kind", list(RETRIABLE))
def test_retriable_failures_are_retried_with_the_same_seed(kind: str) -> None:
    sleeps: list[float] = []
    failure = RETRIABLE[kind]
    planner = make_planner(scripted_client([failure, failure]), sleeps=sleeps)
    calls = Recorder()

    output = planner.plan(first_input(), 1, calls)

    assert output.text == "Day 1:\nLunch: Cafe One, Synthville"
    assert [c.attempt for c in output.calls] == [0, 1, 2]
    assert [type(c.error) for c in output.calls] == [TransportError, TransportError, type(None)]
    assert {c.request.options.seed for c in output.calls} == {1}
    assert len({c.prompt.sha256 for c in output.calls}) == 1
    assert calls.calls == list(output.calls)
    assert sleeps == [RETRY_PAUSE_S, RETRY_PAUSE_S]


@pytest.mark.parametrize("kind", list(RETRIABLE))
def test_after_the_last_retry_there_is_no_text(kind: str) -> None:
    failure = RETRIABLE[kind]
    planner = make_planner(scripted_client([failure] * 3))

    output = planner.plan(first_input(), 0, Recorder())

    assert output.text is None
    assert len(output.calls) == 3  # 1 + transport_retries (2)
    assert all(isinstance(c.error, TransportError) for c in output.calls)


def not_found(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(404, json={"error": "model 'qwen3:8b-q4_K_M' not found"})


def not_json(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"<html>proxy</html>")


def error_field(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"error": "llama runner process has terminated"})


def not_done(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={**generate_reply(""), "done": False})


def bad_shape(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"response": "x", "done": True, "prompt_eval_count": "many"})


HARD = {
    "http_4xx_model_not_found": not_found,
    "body_not_json": not_json,
    "error_field": error_field,
    "not_done": not_done,
    "unexpected_shape": bad_shape,
}


@pytest.mark.parametrize("kind", list(HARD))
def test_every_other_failure_is_a_hard_error_without_retry(kind: str) -> None:
    sleeps: list[float] = []
    planner = make_planner(scripted_client([HARD[kind]]), sleeps=sleeps)
    calls = Recorder()

    with pytest.raises(ServerError):
        planner.plan(first_input(), 0, calls)
    assert len(calls.calls) == 1
    assert isinstance(calls.calls[0].error, ServerError)
    assert sleeps == []


def test_a_warm_up_that_fails_every_attempt_raises() -> None:
    planner = make_planner(scripted_client([refused] * 3))

    with pytest.raises(TransportError):
        planner.warm_up(Recorder())


def test_the_retry_count_comes_from_the_config(tmp_path: Path) -> None:
    planner = make_planner(scripted_client([refused] * 5), transport_retries=0)

    assert len(planner.plan(first_input(), 0, Recorder()).calls) == 1
    assert isinstance(load_run_config().generation, Generation)
