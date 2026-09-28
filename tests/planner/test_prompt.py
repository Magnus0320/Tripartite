"""The planner prompt renderer (ARCHITECTURE.md D3, D6)."""

import dataclasses
import hashlib
import string
from pathlib import Path

import pytest

from tests.fixtures.model.synthetic_tokenizer import expected_user_prompt
from tests.fixtures.model.upstream_prompt import upstream_planner_instruction
from tripartite.config import BASELINE_CONFIG_PATH, SINGLE_CONFIG_PATH, load_run_config
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs
from tripartite.llm.chat_template import ChatTemplate
from tripartite.planner import prompt
from tripartite.planner.prompt import (
    PROMPT_PATH,
    PROMPT_VERSION,
    PromptError,
    PromptRenderer,
    load_template,
    render_prompt,
)

TEMPLATE = 'Plan.\n{{"example": true}}\nGiven information: {text}\nQuery: {query}\nTravel Plan:'


def test_rendering_is_the_chat_template_around_the_formatted_prompt(chat: ChatTemplate) -> None:
    renderer = PromptRenderer(TEMPLATE, chat)

    for inp in load_planner_inputs():
        rendered = renderer.render(inp)
        body = TEMPLATE.format(text=inp.reference_information, query=inp.query)
        assert rendered.text == expected_user_prompt(body)
        assert rendered.sha256 == hashlib.sha256(rendered.text.encode("utf-8")).hexdigest()
        assert rendered.prompt_version == PROMPT_VERSION == "sp-direct-v1"


class Subclass(PlannerInput):
    pass


@pytest.mark.parametrize(
    "value",
    [
        object(),
        {"query_id": "val-001", "query": "q", "reference_information": "r"},
        Subclass("val-001", "q", "r"),
        dataclasses.make_dataclass("PlannerInput", ["query_id", "query", "reference_information"])(
            "val-001", "q", "r"
        ),
    ],
)
def test_anything_but_a_planner_input_is_refused(chat: ChatTemplate, value: object) -> None:
    with pytest.raises(TypeError, match="PlannerInput"):
        PromptRenderer(TEMPLATE, chat).render(value)


def test_render_prompt_refuses_before_loading_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_load() -> PromptRenderer:
        raise AssertionError("loaded before the type check")

    monkeypatch.setattr(prompt, "default_renderer", must_not_load)

    with pytest.raises(TypeError, match="PlannerInput"):
        render_prompt(Subclass("val-001", "q", "r"))


def test_the_template_file_is_checked_against_its_sha256(tmp_path: Path) -> None:
    path = tmp_path / "prompt.txt"
    path.write_bytes(TEMPLATE.encode("utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    assert load_template(path, digest) == TEMPLATE
    path.write_bytes(TEMPLATE.encode("utf-8") + b"\n")
    with pytest.raises(PromptError, match="new prompt version"):
        load_template(path, digest)


# --- the committed prompt (sp-direct-v1) --------------------------------------------------------


def test_prompt_matches_upstream() -> None:
    assert PROMPT_PATH.read_bytes() == upstream_planner_instruction().encode("utf-8")


def test_the_run_configs_record_the_prompt_file() -> None:
    digest = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()

    for path in (BASELINE_CONFIG_PATH, SINGLE_CONFIG_PATH):
        run = load_run_config(path)
        assert run.prompt_path == PROMPT_PATH
        assert (run.prompt.version, run.prompt.sha256) == (PROMPT_VERSION, digest)
        assert load_template(run.prompt_path, run.prompt.sha256) == upstream_planner_instruction()


def test_the_official_prompt_has_exactly_the_two_fields() -> None:
    fields = [f for _, f, _, _ in string.Formatter().parse(upstream_planner_instruction()) if f]

    assert fields == ["text", "query"]
