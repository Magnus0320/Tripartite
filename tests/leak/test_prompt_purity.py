"""D3 test 2, ``test_prompt_purity`` (model; ARCHITECTURE.md D3, D6).

For every input, the rendered prompt bytes equal the chat template around
``PLANNER_INSTRUCTION.format(text=reference_information, query=query)``, built independently
here: the instruction is read from the vendored ``agents/prompts.py`` with ``ast`` (not from
``prompts/``), and the Qwen3 single-user-turn wrapper is written out literally (not rendered
with our jinja code). The prompt is therefore a pure function of the two allowed fields.
In CI this runs over the shared synthetic set; ``local`` runs it over the real 180.
"""

import dataclasses
from pathlib import Path

import pytest

from tests.fixtures.model.synthetic_tokenizer import write_synthetic_tokenizer_dir
from tests.fixtures.model.upstream_prompt import upstream_planner_instruction
from tripartite.config import load_run_config, load_stack
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs
from tripartite.planner.prompt import PromptRenderer, render_prompt


def expected_prompt(inp: PlannerInput) -> bytes:
    body = upstream_planner_instruction().format(text=inp.reference_information, query=inp.query)
    wrapped = f"<|im_start|>user\n{body}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    return wrapped.encode("utf-8")


def test_prompt_purity(tmp_path: Path) -> None:
    stack = load_stack()
    tokenizer_dir = write_synthetic_tokenizer_dir(tmp_path / "tk", stack.tokenizer.revision)
    renderer = PromptRenderer.from_config(load_run_config(), stack, tokenizer_dir=tokenizer_dir)

    inputs = load_planner_inputs()

    assert len(inputs) == 180
    for inp in inputs:
        assert renderer.render(inp).text.encode("utf-8") == expected_prompt(inp)
        other_id = dataclasses.replace(inp, query_id="val-999")
        assert renderer.render(other_id).text == renderer.render(inp).text


def test_prompt_purity_through_the_fake_mode_default() -> None:
    """The production path as CI and web development run it: ``render_prompt`` with fake mode's
    fixed Qwen3 template from ``template_from_env`` (D4 §Fake-mode tokenizer)."""
    inputs = load_planner_inputs()

    assert len(inputs) == 180
    for inp in inputs:
        assert render_prompt(inp).text.encode("utf-8") == expected_prompt(inp)


@pytest.mark.local
def test_prompt_purity_over_the_real_validation_set() -> None:
    inputs = load_planner_inputs()

    assert len(inputs) == 180
    for inp in inputs:
        assert render_prompt(inp).text.encode("utf-8") == expected_prompt(inp)
