"""``tripartite model`` commands (ARCHITECTURE.md D4, D9)."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.fixtures.model.fake_ollama import FakeOllama
from tests.fixtures.model.synthetic_tokenizer import write_synthetic_tokenizer_dir
from tripartite import cli as root_cli
from tripartite.config import StackConfig, serve_env_lines
from tripartite.llm import cli
from tripartite.llm.errors import LLMError
from tripartite.llm.tokenizer import TOKENIZER_FILES, Tokenizer, check_tokenizer_dir

runner = CliRunner()


def test_serve_env_through_the_root_cli(stack: StackConfig) -> None:
    plain = runner.invoke(root_cli.app, ["model", "serve-env"])
    sh = runner.invoke(root_cli.app, ["model", "serve-env", "--format", "sh"])

    assert plain.exit_code == 0, plain.output
    assert plain.output.splitlines() == serve_env_lines(stack)
    assert sh.exit_code == 0, sh.output
    assert sh.output.splitlines() == serve_env_lines(stack, "sh")


def test_serve_env_refuses_an_unknown_format() -> None:
    assert runner.invoke(cli.app, ["serve-env", "--format", "json"]).exit_code != 0


def test_calibrate_refuses_the_fake_client() -> None:
    result = runner.invoke(cli.app, ["calibrate"])  # TRIPARTITE_LLM=fake, as in CI

    assert result.exit_code == 1
    assert "TRIPARTITE_LLM=fake is set; calibration needs the real server" in result.output


# --- pull ---------------------------------------------------------------------------------------


def test_pull_tokenizer_downloads_at_the_pinned_revision(
    stack: StackConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_synthetic_tokenizer_dir(tmp_path / "hub", stack.tokenizer.revision)
    calls: list[dict[str, Any]] = []

    def fake_download(**kwargs: Any) -> str:
        calls.append(kwargs)
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.write_bytes((source / kwargs["filename"]).read_bytes())
        return str(target)

    monkeypatch.setattr(cli, "hf_hub_download", fake_download)
    target = tmp_path / "tokenizer"

    assert cli.pull_tokenizer(stack, target) is True
    assert [c["filename"] for c in calls] == list(TOKENIZER_FILES)
    assert {(c["repo_id"], c["revision"]) for c in calls} == {
        ("Qwen/Qwen3-8B", stack.tokenizer.revision)
    }
    assert check_tokenizer_dir(target, stack.tokenizer.repo, stack.tokenizer.revision) == []
    assert cli.pull_tokenizer(stack, target) is False  # already there: no second download
    assert len(calls) == 2


def test_pull_model_through_the_dedicated_server(stack: StackConfig, tokenizer: Tokenizer) -> None:
    server = FakeOllama.for_stack(stack, tokenizer, pulled=False)

    assert cli.pull_model(stack, server.client()) == "pulled qwen3:8b-q4_K_M"
    assert ("POST", "/api/pull") in [(m, p) for m, p, _b in server.requests]
    server.requests.clear()
    assert "already present" in cli.pull_model(stack, server.client())
    assert ("POST", "/api/pull") not in [(m, p) for m, p, _b in server.requests]


def test_a_pulled_model_with_another_digest_fails(stack: StackConfig, tokenizer: Tokenizer) -> None:
    server = FakeOllama.for_stack(stack, tokenizer, pulled=False, pulled_digest="f" * 64)

    with pytest.raises(LLMError, match="never update the pin"):
        cli.pull_model(stack, server.client())
