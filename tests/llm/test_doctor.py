"""``tripartite model doctor`` against a scripted server (ARCHITECTURE.md D4, D1; A-005, A-022)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from filelock import FileLock

from tests.fixtures.model.fake_ollama import FakeDesktopApp, FakeOllama, server_config_line
from tripartite.config import StackConfig
from tripartite.data import manifest
from tripartite.llm.calibration import CalibrationReport, Probe, write_json
from tripartite.llm.doctor import (
    GO_MAX_DURATION,
    Check,
    DoctorDeps,
    env_value_matches,
    last_server_config,
    log_context_length,
    metal_total_gib,
    parse_cli_version,
    recommended_working_set_mb,
    run_doctor,
    server_config_value,
)
from tripartite.llm.tokenizer import Tokenizer

METAL_LINE = "ggml_metal_init: recommendedMaxWorkingSetSize  = 17179.87 MB"


def data_ok() -> list[manifest.Check]:
    return [manifest.Check("data/MANIFEST.json", "pins", ())]


@pytest.fixture
def world(
    tmp_path: Path, stack: StackConfig, tokenizer: Tokenizer, tokenizer_dir: Path
) -> dict[str, Any]:
    """Everything doctor reads, all passing: a pinned server, its log, the tokenizer, a valid
    calibration, the data checks and the CLI version."""
    log = tmp_path / "ollama-server.log"
    log.write_text(
        "earlier start\n"
        + server_config_line({"OLLAMA_CONTEXT_LENGTH": "4096"})
        + "\n"
        + server_config_line({})
        + "\n"
        + METAL_LINE
        + "\n",
        encoding="utf-8",
    )
    calibration = tmp_path / "token_calibration.json"
    write_json(
        CalibrationReport(
            calibrated_at="2026-09-28T05:00:00Z",
            ollama_version="0.33.2",
            model_tag=stack.model.tag,
            model_digest=stack.model.digest,
            tokenizer_repo=stack.tokenizer.repo,
            tokenizer_revision=stack.tokenizer.revision,
            num_ctx=32768,
            mode="uncached_only",
            probes=[
                Probe(
                    kind="cold",
                    query_id="val-001",
                    prompt_tokens=10,
                    lcp=None,
                    prompt_eval_count=10,
                    prompt_eval_cached_count=None,
                    load_ms=1.0,
                )
            ],
        ),
        calibration,
    )
    return {
        "server": FakeOllama.for_stack(stack, tokenizer),
        "desktop": FakeDesktopApp(running=False),
        "log_path": log,
        "calibration_path": calibration,
        "tokenizer_dir": tokenizer_dir,
        "lock_path": tmp_path / "runs" / ".model.lock",
        "cli_version": lambda _stack: "0.33.2",
        "data_checks": data_ok,
        "wired_limit_mb": lambda: 0,
    }


def doctor(stack: StackConfig, world: dict[str, Any]) -> dict[str, Check]:
    deps = {k: v for k, v in world.items() if k not in ("server", "desktop")}
    checks = run_doctor(
        stack,
        DoctorDeps(client=world["server"].client(), desktop=world["desktop"].client(), **deps),
    )
    return {c.label: c for c in checks}


def failures(checks: dict[str, Check]) -> dict[str, str]:
    return {label: c.detail for label, c in checks.items() if c.level == "fail"}


def test_a_pinned_stack_passes_and_doctor_loads_the_model(
    stack: StackConfig, world: dict[str, Any]
) -> None:
    checks = doctor(stack, world)

    assert failures(checks) == {}
    assert [c.label for c in checks.values() if c.level == "warn"] == [
        "desktop app (127.0.0.1:11434)"
    ]
    loaded = checks["loaded model (/api/ps)"].detail
    assert loaded.startswith("loaded by doctor with the server's default options")
    assert "context_length 32768" in loaded
    assert world["server"].loaded_ctx == 32768  # OLLAMA_CONTEXT_LENGTH, not a request option
    load = [b for m, p, b in world["server"].requests if p == "/api/generate"]
    assert load == [b'{"model":"qwen3:8b-q4_K_M","keep_alive":-1}']
    assert checks["iogpu.wired_limit_mb"].detail == "0 (0 = macOS default)"
    assert checks["recommendedMaxWorkingSetSize"].detail == "17179.87 MB (A-005)"
    assert checks["token calibration"].detail.startswith("valid: mode uncached_only")


def test_an_already_loaded_model_is_not_reloaded(stack: StackConfig, world: dict[str, Any]) -> None:
    world["server"].loaded_ctx = 32768

    checks = doctor(stack, world)

    assert failures(checks) == {}
    assert not any(p == "/api/generate" for _m, p, _b in world["server"].requests)


@pytest.mark.parametrize(
    ("change", "label", "message"),
    [
        (
            {"cli_version": lambda _s: "0.33.1"},
            "ollama --version",
            "client 0.33.1 != pinned 0.33.2",
        ),
        ({"server_version": "0.34.0"}, "server (http://127.0.0.1:11435)", "/api/version 0.34.0"),
        ({"server_ctx": 4096}, "loaded model (/api/ps)", "context length 4096 (from /api/ps)"),
        ({"pulled": False}, "model (/api/tags)", "make pull-model"),
        ({"pulled_digest": "f" * 64}, "model (/api/tags)", "never update the pin"),
        ({"calibration": "{}"}, "token calibration", "invalid"),
        ({"tokenizer_dir": "missing"}, "tokenizer", "make pull-model"),
        ({"desktop_loaded": ["granite4.2"]}, "desktop app (127.0.0.1:11434)", "granite4.2"),
    ],
)
def test_each_pin_that_differs_fails(
    stack: StackConfig,
    world: dict[str, Any],
    tmp_path: Path,
    change: dict[str, Any],
    label: str,
    message: str,
) -> None:
    for key, value in change.items():
        if key == "server_version":
            world["server"].version = value
        elif key in ("server_ctx", "pulled", "pulled_digest"):
            setattr(world["server"], key, value)
        elif key == "calibration":
            world["calibration_path"].write_text(value, encoding="utf-8")
        elif key == "tokenizer_dir":
            world["tokenizer_dir"] = tmp_path / value
        elif key == "desktop_loaded":
            world["desktop"] = FakeDesktopApp(loaded=value)
        else:
            world[key] = value

    failed = failures(doctor(stack, world))

    assert list(failed) == [label]
    assert message in failed[label]


@pytest.mark.parametrize(
    ("log", "message"),
    [
        (None, "missing; start the server with `make serve-model`"),
        ("no config here\n", 'no msg="server config" line'),
        (server_config_line({"OLLAMA_NUM_PARALLEL": "4"}), "OLLAMA_NUM_PARALLEL='4'"),
        (server_config_line({"OLLAMA_CONTEXT_LENGTH": "4096"}), "OLLAMA_CONTEXT_LENGTH='4096'"),
        (server_config_line({"OLLAMA_FLASH_ATTENTION": "false"}), "OLLAMA_FLASH_ATTENTION"),
        (server_config_line({"OLLAMA_KEEP_ALIVE": "5m0s"}), "OLLAMA_KEEP_ALIVE='5m0s'"),
        (server_config_line({"OLLAMA_HOST": "http://127.0.0.1:11434"}), "OLLAMA_HOST"),
    ],
)
def test_a_server_started_with_another_environment_fails(
    stack: StackConfig, world: dict[str, Any], log: str | None, message: str
) -> None:
    if log is None:
        world["log_path"].unlink()
    else:
        world["log_path"].write_text(log + "\n", encoding="utf-8")

    failed = failures(doctor(stack, world))

    assert list(failed) == ["server env (runs/ollama-server.log)"]
    assert message in failed["server env (runs/ollama-server.log)"]


def test_a_server_that_does_not_answer(stack: StackConfig, world: dict[str, Any]) -> None:
    world["server"].handler = world["desktop"].handler  # connection refused

    checks = doctor(stack, world)

    assert list(failures(checks)) == ["server (http://127.0.0.1:11435)"]
    assert "make serve-model" in checks["server (http://127.0.0.1:11435)"].detail
    assert "tokenizer" in checks  # the checks that need no server still run


def test_context_length_falls_back_to_the_log(stack: StackConfig, world: dict[str, Any]) -> None:
    world["server"].report_context_length = False
    log = world["log_path"]
    log.write_text(log.read_text(encoding="utf-8") + "llama_context: n_ctx = 32768\n", "utf-8")

    checks = doctor(stack, world)

    assert failures(checks) == {}
    world["server"].server_ctx = 8192
    world["server"].loaded_ctx = None
    log.write_text(log.read_text(encoding="utf-8") + "llama_context: n_ctx = 8192\n", "utf-8")
    assert "from the server log" in failures(doctor(stack, world))["loaded model (/api/ps)"]


def test_a_held_lock_stops_doctor_from_loading(stack: StackConfig, world: dict[str, Any]) -> None:
    world["lock_path"].parent.mkdir(parents=True)
    with FileLock(world["lock_path"]):
        failed = failures(doctor(stack, world))

    assert "is held by another process" in failed["loaded model (/api/ps)"]


def test_a_second_model_on_the_dedicated_server_fails(
    stack: StackConfig, world: dict[str, Any]
) -> None:
    server = world["server"]
    original = server.handler

    def two_models(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.url.path == "/api/ps":
            models = response.json()["models"] + [{"name": "other", "digest": "0" * 64}]
            return httpx.Response(200, json={"models": models})
        return response

    server.loaded_ctx = 32768
    server.handler = two_models

    assert (
        "expected exactly qwen3:8b-q4_K_M loaded"
        in failures(doctor(stack, world))["loaded model (/api/ps)"]
    )


def test_the_desktop_app_only_ever_gets_ps(stack: StackConfig, world: dict[str, Any]) -> None:
    desktop = FakeDesktopApp()
    world["desktop"] = desktop

    checks = doctor(stack, world)

    assert checks["desktop app (127.0.0.1:11434)"].level == "ok"
    assert desktop.requests == [("GET", "/api/ps")]


def test_missing_and_stale_calibration_are_warnings(
    stack: StackConfig, world: dict[str, Any]
) -> None:
    world["calibration_path"].unlink()
    assert doctor(stack, world)["token calibration"].level == "warn"

    stale = CalibrationReport(
        calibrated_at=datetime(2026, 1, 1, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ollama_version="0.30.0",
        model_tag=stack.model.tag,
        model_digest=stack.model.digest,
        tokenizer_repo=stack.tokenizer.repo,
        tokenizer_revision=stack.tokenizer.revision,
        num_ctx=32768,
        mode="total",
        probes=[],
    )
    write_json(stale, world["calibration_path"])
    check = doctor(stack, world)["token calibration"]
    assert check.level == "warn"
    assert check.detail.startswith("stale: ollama_version '0.30.0' != '0.33.2'")


def test_data_problems_fail(stack: StackConfig, world: dict[str, Any]) -> None:
    world["data_checks"] = lambda: [manifest.Check("data/raw/validation.csv", "x", ("missing",))]

    assert failures(doctor(stack, world)) == {"data verify: data/raw/validation.csv": "missing"}


# --- parsing ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("output", "version"),
    [
        ("ollama version is 0.33.2\n", "0.33.2"),
        ("ollama version is 0.34.0\nWarning: client version is 0.33.2\n", "0.33.2"),
        (
            "Warning: could not connect to a running Ollama instance\n"
            "Warning: client version is 0.33.2\n",
            "0.33.2",
        ),
        ("garbage", None),
    ],
)
def test_parse_cli_version(output: str, version: str | None) -> None:
    assert parse_cli_version(output) == version


def test_server_config_parsing() -> None:
    log = "\n".join(
        [server_config_line({"OLLAMA_CONTEXT_LENGTH": "1"}), "x", server_config_line({}), "y"]
    )
    line = last_server_config(log)

    assert line is not None
    assert server_config_value(line, "OLLAMA_CONTEXT_LENGTH") == "32768"
    assert server_config_value(line, "OLLAMA_HOST") == "http://127.0.0.1:11435"
    assert server_config_value(line, "OLLAMA_NUM_PARALLEL") == "1"
    assert server_config_value(line, "OLLAMA_MISSING") is None
    assert last_server_config("nothing") is None


@pytest.mark.parametrize(
    ("key", "expected", "logged", "ok"),
    [
        ("OLLAMA_HOST", "127.0.0.1:11435", "http://127.0.0.1:11435", True),
        ("OLLAMA_HOST", "127.0.0.1:11435", "http://0.0.0.0:11435", False),
        ("OLLAMA_CONTEXT_LENGTH", "32768", "32768", True),
        ("OLLAMA_CONTEXT_LENGTH", "32768", "", False),
        ("OLLAMA_KEEP_ALIVE", "-1", GO_MAX_DURATION, True),
        ("OLLAMA_KEEP_ALIVE", "-1", "-1", True),
        ("OLLAMA_KEEP_ALIVE", "-1", "5m0s", False),
        ("OLLAMA_FLASH_ATTENTION", "1", "true", True),
        ("OLLAMA_FLASH_ATTENTION", "1", "false", False),
        ("OLLAMA_KV_CACHE_TYPE", "f16", "f16", True),
        ("OLLAMA_KV_CACHE_TYPE", "f16", "", False),
    ],
)
def test_env_value_matches(key: str, expected: str, logged: str, ok: bool) -> None:
    assert env_value_matches(key, expected, logged) is ok


def test_the_metal_total_stands_in_when_the_working_set_is_not_logged(
    stack: StackConfig, world: dict[str, Any]
) -> None:
    world["log_path"].write_text(
        server_config_line({})
        + '\ntime=x msg="inference compute" library=Metal name=MTL0 total="17.8 GiB"\n',
        encoding="utf-8",
    )

    detail = doctor(stack, world)["recommendedMaxWorkingSetSize"].detail

    assert detail == "not logged; Metal total 17.8 GiB from 'inference compute' (A-005)"


def test_log_evidence() -> None:
    log = f"{METAL_LINE}\nx\nggml_metal_device_init: recommendedMaxWorkingSetSize = 18000.00 MB\n"

    assert recommended_working_set_mb(log) == 18000.0
    assert recommended_working_set_mb("") is None
    compute = (
        'time=x level=INFO source=types.go:32 msg="inference compute" id=0 library=Metal '
        'name=MTL0 description="Apple M4 Pro" type=iGPU total="17.8 GiB" available="17.8 GiB"'
    )
    assert metal_total_gib(compute) == 17.8
    assert metal_total_gib("") is None
    assert log_context_length("llama_context: n_ctx = 4096\nrunner --ctx-size 32768 --x") == 32768
    assert log_context_length("") is None
