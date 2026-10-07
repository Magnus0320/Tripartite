"""``GET /api/health`` (D8, FU-19)."""

import inspect
import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tripartite.api.app import app, get_health, stack_path
from tripartite.config import STACK_PATH, load_stack

OLLAMA_PORTS = {11434, 11435}
"""The dedicated server and the desktop app: no test here may contact either."""


def _closed_local_port() -> int:
    """A port on 127.0.0.1 that nothing listens on: bound once, then closed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    assert port not in OLLAMA_PORTS
    return port


@pytest.fixture
def closed_port_stack(tmp_path: Path) -> Iterator[Path]:
    """Point the route at a tmp ``stack.yaml``: the committed one, with the dedicated server
    moved to a closed local port."""
    port = _closed_local_port()
    path = tmp_path / "stack.yaml"
    path.write_text(
        STACK_PATH.read_text(encoding="utf-8").replace("127.0.0.1:11435", f"127.0.0.1:{port}"),
        encoding="utf-8",
    )
    assert load_stack(path).runtime.url == f"http://127.0.0.1:{port}"
    app.dependency_overrides[stack_path] = lambda: path
    yield path
    del app.dependency_overrides[stack_path]


def test_in_fake_mode_all_three_flags_are_true(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_reachable": True,
        "model_digest_ok": True,
        "evaluator_ready": True,
    }


def test_fake_mode_never_reads_stack_yaml(client: TestClient, tmp_path: Path) -> None:
    app.dependency_overrides[stack_path] = lambda: tmp_path / "no-such-stack.yaml"
    try:
        body = client.get("/api/health").json()
    finally:
        del app.dependency_overrides[stack_path]

    assert body["model_reachable"] is True
    assert body["model_digest_ok"] is True


@pytest.mark.usefixtures("closed_port_stack")
@pytest.mark.parametrize("llm", [None, "ollama"])
def test_with_no_server_the_model_flags_are_false_within_3_s(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, llm: str | None
) -> None:
    if llm is None:
        monkeypatch.delenv("TRIPARTITE_LLM")
    else:
        monkeypatch.setenv("TRIPARTITE_LLM", llm)

    start = time.monotonic()
    response = client.get("/api/health")
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_reachable": False,
        "model_digest_ok": False,
        "evaluator_ready": True,  # TRIPARTITE_EVAL_BRIDGE is still fake
    }
    assert elapsed < 3.0


def test_a_missing_stack_yaml_is_false_flags_not_an_error(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")
    app.dependency_overrides[stack_path] = lambda: tmp_path / "no-such-stack.yaml"
    try:
        response = client.get("/api/health")
    finally:
        del app.dependency_overrides[stack_path]

    assert response.status_code == 200
    assert response.json()["model_reachable"] is False
    assert response.json()["model_digest_ok"] is False


def test_the_default_stack_is_the_committed_one() -> None:
    assert stack_path() == STACK_PATH


def test_the_route_is_sync_so_it_runs_in_the_thread_pool() -> None:
    assert not inspect.iscoroutinefunction(get_health)


def test_health_does_not_read_the_data(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    assert client.get("/api/health").status_code == 200


def test_a_server_that_hangs_costs_one_timeout_not_two(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(8)  # connections are accepted by the kernel and never answered
        port: int = silent.getsockname()[1]
        assert port not in OLLAMA_PORTS
        path = tmp_path / "stack.yaml"
        path.write_text(
            STACK_PATH.read_text(encoding="utf-8").replace("127.0.0.1:11435", f"127.0.0.1:{port}"),
            encoding="utf-8",
        )
        app.dependency_overrides[stack_path] = lambda: path
        try:
            start = time.monotonic()
            response = client.get("/api/health")
            elapsed = time.monotonic() - start
        finally:
            del app.dependency_overrides[stack_path]

    assert response.json()["model_reachable"] is False
    assert response.json()["model_digest_ok"] is False
    assert 0.9 < elapsed < 1.8  # each check waits 1.0 s; side by side that is one wait
