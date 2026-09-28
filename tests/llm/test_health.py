"""``model_reachable`` and ``model_digest_ok``, the model flags of ``/api/health`` (ARCHITECTURE.md
D4 §Health checks, D8; FU-17; A-029).

The answers come from the scripted server in ``tests/fixtures/model/fake_ollama.py``. A port with
nothing listening and a socket that never answers are real sockets on 127.0.0.1, so the 1.0 s
total bound is also measured on the real transport.
"""

import socket
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NoReturn

import httpx
import pytest

from tests.fixtures.model.fake_ollama import FakeOllama
from tripartite.config import StackConfig, load_stack
from tripartite.llm.doctor import HEALTH_TIMEOUT_S, model_digest_ok, model_reachable
from tripartite.llm.tokenizer import Tokenizer

Check = Callable[..., bool]
PINNED = load_stack()
TAG = PINNED.model.tag
HEX = PINNED.digest_hex


@pytest.fixture(autouse=True)
def real_mode(fake_mode_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The checks talk to a server only outside fake mode; the fake-mode test sets it again."""
    monkeypatch.delenv("TRIPARTITE_LLM")


@pytest.fixture(params=[model_reachable, model_digest_ok], ids=["reachable", "digest_ok"])
def check(request: pytest.FixtureRequest) -> Check:
    fn: Check = request.param
    return fn


def at(stack: StackConfig, url: str) -> StackConfig:
    return stack.model_copy(update={"runtime": stack.runtime.model_copy(update={"url": url})})


def answering(status: int, body: object) -> httpx.MockTransport:
    """A server that answers every request with ``status`` and ``body`` (JSON unless bytes)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def refusing(error: Exception) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> NoReturn:
        raise error

    return httpx.MockTransport(handler)


def never_called(_request: httpx.Request) -> NoReturn:
    raise AssertionError("the health check sent a request")


@pytest.fixture
def closed_port() -> int:
    """A port on 127.0.0.1 that nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A port whose connections are accepted (into the kernel's backlog) and never answered."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(8)
        yield s.getsockname()[1]


# --- the pinned server ---------------------------------------------------------------------------


def test_the_pinned_server_passes_both_without_loading_the_model(
    stack: StackConfig, tokenizer: Tokenizer
) -> None:
    server = FakeOllama.for_stack(stack, tokenizer)
    transport = httpx.MockTransport(server.handler)

    assert model_reachable(stack, transport=transport) is True
    assert model_digest_ok(stack, transport=transport) is True
    assert [(m, p, b) for m, p, b in server.requests] == [
        ("GET", "/api/version", b""),
        ("GET", "/api/tags", b""),
    ]
    assert server.loaded_ctx is None  # nothing was loaded
    assert server.generated == 0


def test_the_digest_matches_with_or_without_its_prefix(
    stack: StackConfig, tokenizer: Tokenizer
) -> None:
    for digest in (stack.digest_hex, stack.model.digest):
        server = FakeOllama.for_stack(stack, tokenizer, pulled_digest=digest)
        assert model_digest_ok(stack, transport=httpx.MockTransport(server.handler))


@pytest.mark.parametrize(
    "changes", [{"pulled": False}, {"pulled_digest": "f" * 64}], ids=["tag_missing", "other_digest"]
)
def test_a_missing_tag_or_another_digest_is_not_ok(
    stack: StackConfig, tokenizer: Tokenizer, changes: dict[str, object]
) -> None:
    server = FakeOllama.for_stack(stack, tokenizer, **changes)
    transport = httpx.MockTransport(server.handler)

    assert model_digest_ok(stack, transport=transport) is False
    assert model_reachable(stack, transport=transport) is True  # the server itself answers


@pytest.mark.parametrize(
    ("entry", "ok"),
    [
        ({"name": TAG, "model": TAG, "digest": HEX}, True),
        ({"name": "alias:latest", "model": TAG, "digest": HEX}, True),
        ({"name": TAG, "digest": "sha256:" + HEX}, True),
        ({"name": "qwen3:8b", "model": "qwen3:8b", "digest": HEX}, False),
        ({"name": TAG, "model": TAG, "digest": "sha256:" + "0" * 64}, False),
        ({"name": TAG, "model": TAG}, False),
        ({"name": TAG, "model": TAG, "digest": 5}, False),
    ],
    ids=["both", "model_only", "name_only", "other_tag", "other_digest", "no_digest", "bad_type"],
)
def test_the_tag_is_matched_by_name_or_model(entry: dict[str, object], ok: bool) -> None:
    other = {"name": "llama3:8b", "model": "llama3:8b", "digest": "1" * 64}
    transport = answering(200, {"models": [other, entry]})

    assert model_digest_ok(PINNED, transport=transport) is ok


# --- anything else is false, never an exception --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"error": "not found"}),
        (500, {"error": "internal"}),
        (200, b"not json"),
        (200, {"error": "no version and no models"}),
        (200, []),
        (201, {"version": "0.33.2", "models": [{"name": TAG, "model": TAG, "digest": HEX}]}),
    ],
    ids=["404", "500", "not_json", "wrong_fields", "not_an_object", "not_200"],
)
def test_anything_but_a_healthy_answer_is_false(check: Check, status: int, body: object) -> None:
    assert check(PINNED, transport=answering(status, body)) is False


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        RuntimeError("unexpected"),
    ],
    ids=["connect", "read_timeout", "other"],
)
def test_an_exception_is_false(check: Check, error: Exception) -> None:
    assert check(PINNED, transport=refusing(error)) is False


def test_a_slow_answer_is_false_after_one_second_in_total(
    check: Check, stack: StackConfig, tokenizer: Tokenizer
) -> None:
    """The mock transport is never subject to httpx's per-phase timeouts, so this measures the
    check's own total bound."""
    server = FakeOllama.for_stack(stack, tokenizer)

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(2 * HEALTH_TIMEOUT_S)
        return server.handler(request)

    start = time.perf_counter()
    assert check(stack, transport=httpx.MockTransport(slow)) is False
    assert HEALTH_TIMEOUT_S <= time.perf_counter() - start < HEALTH_TIMEOUT_S + 0.5


def test_nothing_listening_is_false_at_once(
    check: Check, stack: StackConfig, closed_port: int
) -> None:
    start = time.perf_counter()
    assert check(at(stack, f"http://127.0.0.1:{closed_port}")) is False
    assert time.perf_counter() - start < HEALTH_TIMEOUT_S


def test_a_server_that_never_answers_is_false_after_one_second(
    check: Check, stack: StackConfig, silent_port: int
) -> None:
    start = time.perf_counter()
    assert check(at(stack, f"http://127.0.0.1:{silent_port}")) is False
    assert time.perf_counter() - start < HEALTH_TIMEOUT_S + 0.5


# --- configs/stack.yaml and the environment ------------------------------------------------------


def test_by_default_configs_stack_yaml_is_read(stack: StackConfig, tokenizer: Tokenizer) -> None:
    server = FakeOllama.for_stack(stack, tokenizer)
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(f"{request.url.host}:{request.url.port}")
        return server.handler(request)

    transport = httpx.MockTransport(handler)

    assert model_reachable(transport=transport) is True
    assert model_digest_ok(transport=transport) is True
    assert hosts == ["127.0.0.1:11435", "127.0.0.1:11435"]


def test_a_missing_or_invalid_stack_file_is_false(check: Check, tmp_path: Path) -> None:
    invalid = tmp_path / "stack.yaml"
    invalid.write_text("schema_version: 2\n", encoding="utf-8")
    transport = httpx.MockTransport(never_called)

    assert check(tmp_path / "missing.yaml", transport=transport) is False
    assert check(invalid, transport=transport) is False


def test_an_invalid_llm_mode_is_false_not_an_error(
    check: Check, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPARTITE_LLM", "real")  # llm_mode() accepts fake, ollama or unset

    assert check(PINNED, transport=httpx.MockTransport(never_called)) is False


def test_fake_mode_is_true_without_any_network(
    check: Check,
    stack: StackConfig,
    tmp_path: Path,
    closed_port: int,
    no_network: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIPARTITE_LLM", "fake")

    assert check() is True
    assert check(at(stack, f"http://127.0.0.1:{closed_port}")) is True
    assert check(tmp_path / "missing.yaml") is True
    assert check(stack, transport=httpx.MockTransport(never_called)) is True
    assert no_network == []
