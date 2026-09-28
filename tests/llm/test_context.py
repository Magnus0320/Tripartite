"""Context measurement, step 1 of ``make measure-context`` (ARCHITECTURE.md D4; A-006)."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tests.fixtures import synthetic_data
from tests.fixtures.model.run_config import run_data
from tripartite.config import StackConfig
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs
from tripartite.llm import cli
from tripartite.llm.chat_template import ChatTemplate
from tripartite.llm.context import (
    load_context_report,
    measure,
    nearest_rank_p95,
    prompt_budget,
    report_json,
    summarize,
)
from tripartite.llm.fake_client import FakeTokenizer
from tripartite.llm.tokenizer import Tokenizer
from tripartite.planner.prompt import PromptRenderer

TEMPLATE = "Plan well.\nGiven information: {text}\nQuery: {query}\nTravel Plan:"


def test_nearest_rank_p95() -> None:
    assert nearest_rank_p95(list(range(1, 101))) == 95
    assert nearest_rank_p95(list(range(180, 0, -1))) == 171  # index ceil(171) - 1 of 1..180
    assert nearest_rank_p95([7]) == 7


def test_summarize() -> None:
    s = summarize([4, 1, 3, 2])

    assert (s.min, s.median, s.p95, s.max) == (1, 2.5, 4, 4)
    with pytest.raises(ValueError, match="nothing"):
        summarize([])


def test_prompt_budget_is_28416_for_phase_1() -> None:
    assert prompt_budget(32768, 4096) == 28416


def render_with(chat: ChatTemplate) -> "PromptRenderer":
    return PromptRenderer(TEMPLATE, chat)


def test_measure_over_the_synthetic_set(
    tokenizer: Tokenizer, chat: ChatTemplate, stack: StackConfig
) -> None:
    inputs = load_planner_inputs()
    renderer = render_with(chat)

    report = measure(
        inputs,
        lambda i: renderer.render(i).text,
        tokenizer,
        stack=stack,
        num_predict=4096,
        prompt_version="sp-test",
        prompt_sha256="a" * 64,
    )

    assert [q.query_id for q in report.per_query] == [f"val-{i:03d}" for i in range(1, 181)]
    first = report.per_query[0]
    ref = synthetic_data.ref_line(1)
    assert first.ref_chars == len(ref)
    assert first.ref_tokens == len(ref.encode("utf-8"))  # one synthetic token per byte
    assert first.prompt_tokens == tokenizer.count(renderer.render(inputs[0]).text)
    prompt_max = max(q.prompt_tokens for q in report.per_query)
    assert report.summary["prompt_tokens"].max == prompt_max
    assert list(report.summary) == ["ref_chars", "ref_tokens", "prompt_tokens"]
    assert report.headroom_tokens == 28416 - prompt_max
    assert report.fits
    assert (report.tokenizer, report.revision) == ("Qwen/Qwen3-8B", stack.tokenizer.revision)
    assert (report.num_ctx, report.num_predict) == (32768, 4096)


def test_a_fake_count_is_recorded_as_fake(chat: ChatTemplate, stack: StackConfig) -> None:
    renderer = render_with(chat)

    report = measure(
        load_planner_inputs()[:3],
        lambda i: renderer.render(i).text,
        FakeTokenizer(),
        stack=stack,
        num_predict=4096,
        prompt_version="v",
        prompt_sha256="a" * 64,
    )

    assert (report.tokenizer, report.revision) == ("fake-bytes", "v1")


def test_it_does_not_fit_when_the_budget_is_exceeded(
    tokenizer: Tokenizer, chat: ChatTemplate, stack: StackConfig
) -> None:
    renderer = render_with(chat)
    long_input = PlannerInput("val-001", "q", "x" * 28_500)

    report = measure(
        [long_input],
        lambda i: renderer.render(i).text,
        tokenizer,
        stack=stack,
        num_predict=4096,
        prompt_version="sp-test",
        prompt_sha256="a" * 64,
    )

    assert not report.fits
    assert report.headroom_tokens < 0


def test_the_report_round_trips(
    tokenizer: Tokenizer, chat: ChatTemplate, stack: StackConfig, tmp_path: Path
) -> None:
    renderer = render_with(chat)
    report = measure(
        load_planner_inputs()[:3],
        lambda i: renderer.render(i).text,
        tokenizer,
        stack=stack,
        num_predict=4096,
        prompt_version="v",
        prompt_sha256="a" * 64,
    )
    path = tmp_path / "context_report.json"
    path.write_text(report_json(report), encoding="utf-8")

    assert load_context_report(path) == report
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [
        "tokenizer",
        "revision",
        "num_ctx",
        "num_predict",
        "prompt_version",
        "prompt_sha256",
        "per_query",
        "summary",
        "fits",
        "headroom_tokens",
    ]
    assert load_context_report(tmp_path / "missing.json") is None
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="does not validate"):
        load_context_report(path)


# --- the CLI command, with the tokenizer and prompt injected -----------------------------------


@pytest.fixture
def run_config(tmp_path: Path) -> Path:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(TEMPLATE, encoding="utf-8")
    data = run_data()
    data["prompt"]["sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
    path = tmp_path / "baseline.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def injected(monkeypatch: pytest.MonkeyPatch, tokenizer: Tokenizer, chat: ChatTemplate) -> None:
    monkeypatch.setattr(cli, "tokenizer_from_env", lambda _stack: tokenizer)
    monkeypatch.setattr(
        cli.PromptRenderer,
        "from_config",
        classmethod(lambda _cls, _run, _stack: PromptRenderer(TEMPLATE, chat)),
    )


@pytest.mark.usefixtures("injected")
def test_measure_context_command(run_config: Path, tmp_path: Path) -> None:
    out = tmp_path / "reports" / "context_report.json"

    result = CliRunner().invoke(
        cli.app, ["measure-context", "--config", str(run_config), "--out", str(out)]
    )

    assert result.exit_code == 0, result.output
    report = load_context_report(out)
    assert report is not None
    assert report.fits
    assert "against 32768 - 4096 - 256 = 28416" in result.output
    assert "fits: true" in result.output


@pytest.mark.usefixtures("injected")
def test_measure_context_fails_when_it_does_not_fit(run_config: Path, tmp_path: Path) -> None:
    data = yaml.safe_load(run_config.read_text(encoding="utf-8"))
    data["generation"]["num_predict"] = 32_500
    run_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    out = tmp_path / "context_report.json"

    result = CliRunner().invoke(
        cli.app, ["measure-context", "--config", str(run_config), "--out", str(out)]
    )

    assert result.exit_code == 1
    assert "fits: false" in result.output
    assert "architecture question" in result.output
    assert out.exists()  # the failing report is still written, for the record


def test_measure_context_fails_cleanly_without_a_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli.app, ["measure-context", "--config", str(tmp_path / "none.yaml")]
    )

    assert result.exit_code == 1
    assert "none.yaml: missing" in result.output
    assert result.output.splitlines()[-1] == "model measure-context: FAILED"
