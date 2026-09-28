"""Fake mode's tokenizer and chat template (ARCHITECTURE.md D4 §Fake-mode tokenizer, v0.8).

CI has no network and no ``data/tokenizer/``. With ``TRIPARTITE_LLM=fake`` everything that renders
or counts a prompt must still work, through ``tokenizer_from_env()`` and ``template_from_env()``,
and a fake count must never pass for a real one.
"""

from pathlib import Path

import jinja2
import pytest
from typer.testing import CliRunner

from tests.fixtures.model.upstream_prompt import upstream_planner_instruction
from tripartite.config import StackConfig, load_run_config
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.llm import chat_template, cli
from tripartite.llm import tokenizer as tokenizer_module
from tripartite.llm.calibration import post_check
from tripartite.llm.chat_template import FAKE_CHAT_TEMPLATE, ChatTemplate, template_from_env
from tripartite.llm.context import load_context_report
from tripartite.llm.errors import TokenizerError
from tripartite.llm.fake_client import FAKE_TOKENIZER_ID, FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateOptions, GenerateRequest
from tripartite.llm.tokenizer import tokenizer_from_env
from tripartite.planner import prompt
from tripartite.planner.prompt import PromptRenderer, render_prompt


def d4_user_prompt(content: str) -> str:
    """D4's fixed Qwen3 non-thinking template around one user turn, written out literally."""
    return f"<|im_start|>user\n{content}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def without_tokenizer_dir(stack: StackConfig) -> StackConfig:
    """``stack`` with ``tokenizer.local_dir`` naming a folder that does not exist."""
    tokenizer = stack.tokenizer.model_copy(update={"local_dir": "data/no-tokenizer-in-this-test"})
    absent = stack.model_copy(update={"tokenizer": tokenizer})
    assert not absent.tokenizer_dir.exists()
    return absent


@pytest.fixture
def real_loaders_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every way to the real tokenizer files fail, so a pass proves they were never read,
    whether or not ``make pull-model`` has filled ``data/tokenizer/`` on this machine."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fake mode reached the real tokenizer files")

    monkeypatch.setattr(tokenizer_module, "load_tokenizer", refuse)
    monkeypatch.setattr(tokenizer_module, "check_tokenizer_dir", refuse)
    monkeypatch.setattr(chat_template, "load_chat_template", refuse)
    monkeypatch.setattr(chat_template, "check_tokenizer_dir", refuse)
    monkeypatch.setattr(prompt, "load_chat_template", refuse)
    monkeypatch.setattr(cli, "hf_hub_download", refuse)
    prompt._default_renderer.cache_clear()  # build the production renderer inside the test


def test_the_fake_tokenizer_is_byte_level() -> None:
    tk = FakeTokenizer()

    assert tk.id == FAKE_TOKENIZER_ID == "fake-bytes@v1"
    assert tk.encode_ids("Aé") == [0x41, 0xC3, 0xA9]
    assert tk.count("") == 0
    assert tk.count("é") == 2
    assert tk.count("<|im_start|>") == 12  # no special tokens: every byte counts
    text = d4_user_prompt("Query: ✈ to Charlotte")
    assert tk.decode(tk.encode_ids(text)) == text
    assert tk.decode(tk.encode_ids("é")[:1]) == "�"  # a character cut in half


def test_fake_mode_selects_the_fake_tokenizer_and_template() -> None:
    assert isinstance(tokenizer_from_env(), FakeTokenizer)  # TRIPARTITE_LLM=fake, as in CI
    assert template_from_env().source == FAKE_CHAT_TEMPLATE


def test_otherwise_the_defaults_are_the_pinned_files(
    stack: StackConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")
    absent = without_tokenizer_dir(stack)

    with pytest.raises(TokenizerError, match="make pull-model"):
        tokenizer_from_env(absent)
    with pytest.raises(TokenizerError, match="make pull-model"):
        template_from_env(absent)


def test_the_fake_template_is_d4s_non_thinking_template(chat: ChatTemplate) -> None:
    fake = template_from_env()
    text = 'Given information: {"a": "ü"}\nQuery: "x"\tü\nTravel Plan:'

    assert fake.render_user_prompt(text) == d4_user_prompt(text)
    assert fake.render_user_prompt(text) == chat.render_user_prompt(text)  # same structure
    with pytest.raises(jinja2.TemplateError, match="non-thinking only"):
        fake.render(
            [{"role": "user", "content": "q"}], add_generation_prompt=True, enable_thinking=True
        )


@pytest.mark.usefixtures("real_loaders_refuse")
def test_fake_mode_renders_and_counts_without_tokenizer_files_or_network(
    stack: StackConfig, no_network: list[str]
) -> None:
    absent = without_tokenizer_dir(stack)
    run = load_run_config()
    inp = load_planner_inputs()[0]
    expected = d4_user_prompt(
        upstream_planner_instruction().format(text=inp.reference_information, query=inp.query)
    )

    rendered = render_prompt(inp)  # the production path the pipeline and the API use
    assert rendered.text == expected
    assert PromptRenderer.from_config(run, absent).render(inp).text == expected
    for tokenizer in (tokenizer_from_env(), tokenizer_from_env(absent)):
        assert tokenizer.id == "fake-bytes@v1"
        assert tokenizer.count(expected) == len(expected.encode("utf-8"))
    assert template_from_env(absent).render_user_prompt("x") == d4_user_prompt("x")

    tokenizer = tokenizer_from_env()
    prompt_tokens = tokenizer.count(rendered.text)
    request = GenerateRequest(
        absent.model.tag, rendered.text, GenerateOptions.production(absent, run.generation, seed=0)
    )
    result = FakeClient(tokenizer).generate(request)
    assert result.prompt_eval_count == prompt_tokens
    check = post_check(
        "total",
        prompt_tokens=prompt_tokens,
        lcp=0,
        prompt_eval_count=result.prompt_eval_count,
        prompt_eval_cached_count=None,
    )
    assert check.ok
    assert no_network == []


@pytest.mark.usefixtures("real_loaders_refuse")
def test_measure_context_runs_in_fake_mode_and_says_so(
    tmp_path: Path, no_network: list[str]
) -> None:
    out = tmp_path / "context_report.json"

    result = CliRunner().invoke(cli.app, ["measure-context", "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = load_context_report(out)
    assert report is not None
    assert (report.tokenizer, report.revision) == ("fake-bytes", "v1")
    assert len(report.per_query) == 180
    assert report.fits
    assert no_network == []
