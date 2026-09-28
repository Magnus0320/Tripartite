"""``configs/stack.yaml``, the run configs and ``config_hash`` (ARCHITECTURE.md D4, D7, §6)."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.fixtures.model.run_config import run_data
from tripartite.config import (
    BASELINE_CONFIG_PATH,
    SINGLE_CONFIG_PATH,
    STACK_PATH,
    ConfigError,
    RunConfig,
    StackConfig,
    config_hash,
    load_run_config,
    load_stack,
    serve_env_lines,
)

# The D4 table, written out here independently of the code.
D4_ENV = {
    "OLLAMA_HOST": "127.0.0.1:11435",
    "OLLAMA_CONTEXT_LENGTH": "32768",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_KEEP_ALIVE": "-1",
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "f16",
}


def stack_data() -> dict[str, Any]:
    data = yaml.safe_load(STACK_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def write_yaml(path: Path, data: object) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_committed_stack_holds_the_pins() -> None:
    stack = load_stack()

    assert stack.runtime.version == "0.33.2"
    assert stack.runtime.url == "http://127.0.0.1:11435"
    assert stack.runtime.desktop_app_url == "http://127.0.0.1:11434"
    assert stack.runtime.env == D4_ENV
    assert list(stack.runtime.env) == list(D4_ENV)
    assert stack.model.tag == "qwen3:8b-q4_K_M"
    assert stack.model.digest == (
        "sha256:500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
    )
    assert stack.model.quant == "q4_K_M"
    assert stack.model.num_ctx == 32768
    assert stack.tokenizer.repo == "Qwen/Qwen3-8B"
    assert stack.tokenizer.revision == "b968826d9c46dd6066d109eabc6255188de91218"
    assert stack.tokenizer.local_dir == "data/tokenizer"
    assert stack.tokenizer_id == "Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218"
    assert stack.digest_hex == stack.model.digest.removeprefix("sha256:")


def edit(data: dict[str, Any], dotted: str, value: object) -> dict[str, Any]:
    *parents, last = dotted.split(".")
    node = data
    for key in parents:
        node = node[key]
    if value is DELETE:
        del node[last]
    else:
        node[last] = value
    return data


DELETE = object()


@pytest.mark.parametrize(
    ("dotted", "value", "message"),
    [
        ("runtime.log_path", "runs/ollama-server.log", "log_path"),
        ("extra", 1, "extra"),
        ("runtime.env.OLLAMA_NUM_PARALLEL", "2", "OLLAMA_NUM_PARALLEL"),
        ("runtime.env.OLLAMA_CONTEXT_LENGTH", "4096", "OLLAMA_CONTEXT_LENGTH"),
        ("runtime.env.OLLAMA_KV_CACHE_TYPE", DELETE, "OLLAMA_KV_CACHE_TYPE"),
        ("runtime.env.OLLAMA_DEBUG", "1", "OLLAMA_DEBUG"),
        ("runtime.env.OLLAMA_HOST", "127.0.0.1:11434", "OLLAMA_HOST"),
        ("runtime.env.OLLAMA_NUM_PARALLEL", 1, "string"),
        ("runtime.version", "0.33", "version"),
        ("runtime.url", "http://localhost:11435", "127.0.0.1"),
        ("runtime.desktop_app_url", "http://127.0.0.1:11435", "differ"),
        ("model.tag", "qwen3:8b", "tag"),
        ("model.digest", "sha256:" + "0" * 64, "500a1f067a9f"),
        ("model.digest", "500a1f067a9f", "digest"),
        ("model.num_ctx", 40960, "num_ctx"),
        ("tokenizer.revision", "main", "revision"),
        ("tokenizer.local_dir", "/tmp/tokenizer", "relative"),
        ("tokenizer.local_dir", "data/../../x", "relative"),
        ("schema_version", 2, "schema_version"),
    ],
)
def test_stack_refuses_drift(tmp_path: Path, dotted: str, value: object, message: str) -> None:
    path = write_yaml(tmp_path / "stack.yaml", edit(stack_data(), dotted, value))

    with pytest.raises(ConfigError, match=message):
        load_stack(path)


def test_a_smaller_consistent_context_is_accepted(tmp_path: Path) -> None:
    data = edit(stack_data(), "model.num_ctx", 16384)
    edit(data, "runtime.env.OLLAMA_CONTEXT_LENGTH", "16384")

    assert load_stack(write_yaml(tmp_path / "stack.yaml", data)).model.num_ctx == 16384


def test_missing_and_malformed_files_are_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_stack(tmp_path / "nope.yaml")
    (tmp_path / "bad.yaml").write_text("runtime: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_stack(tmp_path / "bad.yaml")


def test_serve_env_lines(stack: StackConfig) -> None:
    assert serve_env_lines(stack) == [f"{k}={v}" for k, v in D4_ENV.items()]
    assert serve_env_lines(stack, "sh") == [f"export {k}='{v}'" for k, v in D4_ENV.items()]


def test_sh_format_round_trips_through_the_shell(stack: StackConfig) -> None:
    """What ``make serve-model`` does: ``set -a; eval "$env_sh"; set +a``, then run a program."""
    script = 'set -a; eval "$1"; set +a; env'
    env_sh = "\n".join(serve_env_lines(stack, "sh"))

    out = subprocess.run(
        ["sh", "-c", script, "sh", env_sh], capture_output=True, text=True, check=True
    ).stdout

    exported = dict(line.split("=", 1) for line in out.splitlines() if line.startswith("OLLAMA_"))
    assert exported == D4_ENV


def test_sh_quoting_survives_a_single_quote(stack: StackConfig) -> None:
    runtime = stack.runtime.model_copy(update={"env": {"OLLAMA_X": "it's $HOME"}})
    odd = stack.model_copy(update={"runtime": runtime})

    (line,) = serve_env_lines(odd, "sh")
    out = subprocess.run(
        ["sh", "-c", 'eval "$1"; printf %s "$OLLAMA_X"', "sh", line],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "it's $HOME"


# --- run configs --------------------------------------------------------------------------------


def test_a_batch_and_a_single_config_validate() -> None:
    batch = RunConfig.model_validate(run_data())
    single = RunConfig.model_validate(
        run_data(run={"name": "single"}, kind="single", queries=["val-001"], seeds=[0])
    )

    assert batch.queries == "all"
    assert single.queries == ["val-001"]


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "single"},
        {"kind": "single", "queries": ["val-001", "val-002"], "seeds": [0]},
        {"kind": "single", "queries": ["val-001"], "seeds": [0, 1]},
        {"split": "test"},
        {"split": "train"},
        {"seeds": [0, 0]},
        {"seeds": []},
        {"queries": []},
        {"queries": ["val-1"]},
        {"queries": ["val-001", "val-001"]},
        {"order": "query-major"},
        {"stack": "/etc/stack.yaml"},
        {"unknown": 1},
    ],
)
def test_run_config_refuses(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error"):
        RunConfig.model_validate(run_data(**changes))


def test_thinking_cannot_be_turned_on() -> None:
    data = run_data()
    data["generation"]["think"] = True

    with pytest.raises(ValueError, match="think"):
        RunConfig.model_validate(data)


def test_load_run_config_names_the_file(tmp_path: Path) -> None:
    path = write_yaml(tmp_path / "run.yaml", run_data(kind="nope"))

    with pytest.raises(ConfigError, match=r"run\.yaml: invalid"):
        load_run_config(path)


def test_config_hash_is_canonical_json_without_run_name() -> None:
    data = run_data()
    expected_input = json.loads(json.dumps(data))
    del expected_input["run"]["name"]
    expected = hashlib.sha256(
        json.dumps(
            expected_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    assert config_hash(data) == expected
    assert config_hash(run_data(run={"name": "renamed"})) == expected
    assert config_hash(dict(reversed(list(data.items())))) == expected
    assert config_hash(run_data(seeds=[0, 1])) != expected
    assert data["run"] == {"name": "baseline"}  # the input is not modified


# --- the committed run configs -----------------------------------------------------------------


def test_committed_baseline_is_the_d4_baseline() -> None:
    run = load_run_config(BASELINE_CONFIG_PATH)

    assert (run.kind, run.queries, run.seeds, run.order) == (
        "batch",
        "all",
        [0, 1, 2],
        "seed-major",
    )
    assert (run.mode, run.context_mode, run.split) == ("sole-planning", "full", "validation")
    assert load_stack(run.stack_path) == load_stack()
    assert run.generation.model_dump() == {
        "num_predict": 4096,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
        "think": False,
        "stop": ["<|im_end|>", "<|endoftext|>"],
        "timeout_s": 600,
        "transport_retries": 2,
    }


def test_single_differs_from_baseline_only_where_d8_says() -> None:
    baseline = load_run_config(BASELINE_CONFIG_PATH).model_dump()
    single = load_run_config(SINGLE_CONFIG_PATH).model_dump()

    differing = {key for key in baseline if baseline[key] != single[key]}
    assert differing == {"run", "kind", "queries", "seeds"}
    assert (single["kind"], single["queries"], single["seeds"]) == ("single", ["val-001"], [0])
