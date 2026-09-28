"""The chat template renderer (ARCHITECTURE.md D4, D6; A-015)."""

import json
from pathlib import Path

import jinja2
import pytest
from jinja2.exceptions import SecurityError

from tests.fixtures.model.synthetic_tokenizer import expected_user_prompt
from tripartite.config import StackConfig
from tripartite.llm.chat_template import ChatTemplate, load_chat_template
from tripartite.llm.errors import TokenizerError
from tripartite.llm.tokenizer import write_marker


def test_one_user_turn_with_thinking_off(chat: ChatTemplate) -> None:
    text = 'Given information: {"a": 1}\nQuery: "x"\tü\nTravel Plan:'

    assert chat.render_user_prompt(text) == expected_user_prompt(text)


def test_thinking_on_leaves_the_think_block_out(chat: ChatTemplate) -> None:
    rendered = chat.render(
        [{"role": "user", "content": "q"}], add_generation_prompt=True, enable_thinking=True
    )

    assert rendered == "<|im_start|>user\nq<|im_end|>\n<|im_start|>assistant\n"


def test_environment_matches_hf() -> None:
    """trim_blocks, lstrip_blocks, loopcontrols, tojson keeping non-ASCII, raise_exception."""
    source = (
        "{% for m in messages %}\n"
        "  {% if loop.index > 2 %}{% break %}{% endif %}\n"
        "{{ m.content | tojson }};\n"
        "{% endfor %}"
    )
    rendered = ChatTemplate(source).render(
        [{"role": "user", "content": c} for c in ("ü", "b", "c")],
        add_generation_prompt=False,
        enable_thinking=False,
    )

    assert rendered == '"ü";\n"b";\n'
    with pytest.raises(jinja2.TemplateError, match="boom"):
        ChatTemplate("{{ raise_exception('boom') }}").render_user_prompt("x")


def test_the_sandbox_is_immutable() -> None:
    with pytest.raises(SecurityError):
        ChatTemplate("{{ messages.append(1) }}").render_user_prompt("x")


def test_a_config_without_a_template_is_refused(tokenizer_dir: Path, stack: StackConfig) -> None:
    (tokenizer_dir / "tokenizer_config.json").write_text(json.dumps({}), encoding="utf-8")
    write_marker(tokenizer_dir, stack.tokenizer.repo, stack.tokenizer.revision)

    with pytest.raises(TokenizerError, match="no chat_template"):
        load_chat_template(stack, tokenizer_dir)


def test_the_template_is_checked_against_the_pin(tokenizer_dir: Path, stack: StackConfig) -> None:
    write_marker(tokenizer_dir, stack.tokenizer.repo, "e" * 40)

    with pytest.raises(TokenizerError, match="make pull-model"):
        load_chat_template(stack, tokenizer_dir)
