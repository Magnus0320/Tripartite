"""The Ollama HTTP client (ARCHITECTURE.md D4 §API, D6)."""

import json

import httpx
import pytest

from tripartite.config import Generation, StackConfig
from tripartite.llm.errors import ServerError, TransportError
from tripartite.llm.ollama_client import (
    DesktopApp,
    GenerateOptions,
    GenerateRequest,
    OllamaClient,
    PullProgress,
    build_generate_body,
    llm_mode,
)

URL = "http://127.0.0.1:11435"

OPTIONS = GenerateOptions(
    num_ctx=32768,
    num_predict=4096,
    temperature=0.7,
    top_p=0.8,
    top_k=20,
    min_p=0.0,
    repeat_penalty=1.0,
    seed=2,
    stop=("<|im_end|>", "<|endoftext|>"),
)
REQUEST = GenerateRequest(model="qwen3:8b-q4_K_M", prompt='<|im_start|>user\n"ü"', options=OPTIONS)


def client_for(transport: httpx.MockTransport) -> OllamaClient:
    return OllamaClient(URL, transport=transport)


def test_body_is_exactly_the_d4_request() -> None:
    expected = (
        '{"model":"qwen3:8b-q4_K_M","prompt":"<|im_start|>user\\n\\"ü\\"","raw":true,'
        '"stream":false,"keep_alive":-1,"think":false,"options":{"num_ctx":32768,'
        '"num_predict":4096,"temperature":0.7,"top_p":0.8,"top_k":20,"min_p":0.0,'
        '"repeat_penalty":1.0,"seed":2,"stop":["<|im_end|>","<|endoftext|>"]}}'
    )

    assert build_generate_body(REQUEST) == expected.encode("utf-8")


def test_production_options_come_from_the_stack_and_the_generation_config(
    stack: StackConfig,
) -> None:
    generation = Generation(
        num_predict=4096,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        repeat_penalty=1.0,
        think=False,
        stop=["<|im_end|>", "<|endoftext|>"],
        timeout_s=600,
        transport_retries=2,
    )

    assert GenerateOptions.production(stack, generation, seed=2) == OPTIONS
    probe = GenerateOptions.production(stack, generation, seed=0, num_predict=1)
    assert (probe.num_predict, probe.seed, probe.num_ctx) == (1, 0, 32768)


def test_generate_sends_the_body_and_parses_the_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "response": "Day 1:",
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 120,
                "eval_count": 7,
                "load_duration": 2_500_000,
                "prompt_eval_duration": 300_000_000,
                "eval_duration": 90_000_000,
                "total_duration": 400_000_000,
            },
        )

    with client_for(httpx.MockTransport(handler)) as client:
        result = client.generate(REQUEST)

    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/api/generate")
    assert request.content == build_generate_body(REQUEST)
    assert request.headers["content-type"] == "application/json"
    assert result.text == "Day 1:"
    assert (result.done_reason, result.prompt_eval_count, result.eval_count) == ("stop", 120, 7)
    assert result.prompt_eval_cached_count is None
    assert (result.load_ms, result.prefill_ms, result.generation_ms, result.total_ms) == (
        2.5,
        300.0,
        90.0,
        400.0,
    )
    assert result.wall_ms >= 0


def test_omitted_counts_are_none() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"done": True}))

    result = client_for(transport).generate(REQUEST)

    assert result.text == ""
    assert (result.prompt_eval_count, result.eval_count, result.load_ms) == (None, None, None)


def raises(exc: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("transport", "error", "message"),
    [
        (raises(httpx.ConnectError("refused")), TransportError, "ConnectError"),
        (raises(httpx.ReadTimeout("slow")), TransportError, "timed out after 600 s"),
        (
            httpx.MockTransport(lambda _r: httpx.Response(500, json={"error": "oom"})),
            TransportError,
            "HTTP 500: oom",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(503, text="busy")),
            TransportError,
            "HTTP 503: busy",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(404, json={"error": "no model"})),
            ServerError,
            "HTTP 404: no model",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(200, text="<html>")),
            ServerError,
            "not JSON",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(200, json={"error": "bad"})),
            ServerError,
            "bad",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(200, json={"done": False})),
            ServerError,
            "not done",
        ),
        (
            httpx.MockTransport(lambda _r: httpx.Response(200, json={"done": "maybe"})),
            ServerError,
            "unexpected response",
        ),
    ],
)
def test_errors_are_classified(
    transport: httpx.MockTransport, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        client_for(transport).generate(REQUEST)


def test_load_unload_ps_tags_and_version() -> None:
    bodies: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append((request.url.path, request.content))
        return {
            "/api/generate": httpx.Response(200, json={"done": True, "done_reason": "load"}),
            "/api/ps": httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "m",
                            "model": "m",
                            "digest": "ab",
                            "context_length": 32768,
                            "size": 10,
                            "size_vram": 9,
                            "expires_at": "x",
                            "details": {},
                        }
                    ]
                },
            ),
            "/api/tags": httpx.Response(
                200, json={"models": [{"name": "m", "model": "m", "digest": "ab", "size": 5}]}
            ),
            "/api/version": httpx.Response(200, json={"version": "0.33.2"}),
        }[request.url.path]

    client = client_for(httpx.MockTransport(handler))
    client.load("m")
    client.unload("m")
    (running,) = client.ps()
    (local,) = client.tags()

    assert client.version() == "0.33.2"
    assert bodies[0] == ("/api/generate", b'{"model":"m","keep_alive":-1}')
    assert bodies[1] == ("/api/generate", b'{"model":"m","keep_alive":0}')
    assert (running.name, running.digest, running.context_length) == ("m", "ab", 32768)
    assert (local.name, local.digest) == ("m", "ab")


def test_ps_without_context_length() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, json={"models": [{"name": "m", "digest": "ab"}]})
    )

    assert client_for(transport).ps()[0].context_length is None


def pull_transport(lines: list[dict[str, object]]) -> httpx.MockTransport:
    content = b"\n".join(json.dumps(x).encode() for x in lines) + b"\n"
    return httpx.MockTransport(lambda _r: httpx.Response(200, content=content))


def test_pull_streams_progress() -> None:
    seen: list[PullProgress] = []
    lines: list[dict[str, object]] = [
        {"status": "pulling manifest"},
        {"status": "pulling a3de", "digest": "sha256:a3de", "total": 10, "completed": 5},
        {"status": "success"},
    ]

    client_for(pull_transport(lines)).pull("m", seen.append)

    assert [p.status for p in seen] == ["pulling manifest", "pulling a3de", "success"]
    assert (seen[1].total, seen[1].completed) == (10, 5)


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ([{"status": "pulling manifest"}, {"error": "manifest unknown"}], "manifest unknown"),
        ([{"status": "pulling manifest"}], "not 'success'"),
    ],
)
def test_pull_failures(lines: list[dict[str, object]], message: str) -> None:
    with pytest.raises(ServerError, match=message):
        client_for(pull_transport(lines)).pull("m", lambda _p: None)


def test_desktop_app_is_read_only() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"models": []}))
    desktop = DesktopApp("http://127.0.0.1:11434", transport=transport)

    assert desktop.ps() == []
    for method in ("generate", "load", "unload", "pull", "tags"):
        assert not hasattr(desktop, method)


@pytest.mark.parametrize(
    ("value", "mode"), [(None, "ollama"), ("", "ollama"), ("ollama", "ollama"), ("fake", "fake")]
)
def test_llm_mode(monkeypatch: pytest.MonkeyPatch, value: str | None, mode: str) -> None:
    if value is None:
        monkeypatch.delenv("TRIPARTITE_LLM", raising=False)
    else:
        monkeypatch.setenv("TRIPARTITE_LLM", value)

    assert llm_mode() == mode


def test_llm_mode_refuses_other_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPARTITE_LLM", "openai")

    with pytest.raises(ValueError, match="TRIPARTITE_LLM"):
        llm_mode()
