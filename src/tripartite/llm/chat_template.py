"""The Qwen3 chat template, rendered by us (ARCHITECTURE.md D4, D6; A-015).

The template is the ``chat_template`` string of ``tokenizer_config.json`` at the pinned revision,
checked by the same marker as the tokenizer. It is rendered with jinja2 the way HF
``apply_chat_template`` renders it: an immutable sandbox with ``trim_blocks`` and
``lstrip_blocks``, the ``loopcontrols`` extension, a ``tojson`` filter that keeps non-ASCII text,
and a ``raise_exception`` global. The result is sent with ``raw: true``, so the local token
count covers exactly the bytes the runtime sees.

A planner prompt is one user turn with no system message (D6), followed by the generation prompt
with thinking off: ``enable_thinking=False`` makes the template write an empty
``<think>\\n\\n</think>\\n\\n`` block (D4). No ``/no_think`` text is added.

Fake mode has no tokenizer folder, so ``template_from_env()`` gives it ``FAKE_CHAT_TEMPLATE``, a
fixed Qwen3 non-thinking template committed here, and the pinned template otherwise (D4
§Fake-mode tokenizer). A single user turn renders to the same bytes with either.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NoReturn

import jinja2
from jinja2.ext import loopcontrols
from jinja2.sandbox import ImmutableSandboxedEnvironment

from tripartite.config import StackConfig, load_stack
from tripartite.llm.errors import TokenizerError
from tripartite.llm.ollama_client import llm_mode
from tripartite.llm.tokenizer import check_tokenizer_dir

FAKE_CHAT_TEMPLATE: Final = (
    "{%- if enable_thinking is not defined or enable_thinking %}"
    "{{- raise_exception('the fake chat template is non-thinking only') }}"
    "{%- endif %}"
    "{%- for message in messages %}"
    "{{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>\\n' }}"
    "{%- endfor %}"
    "{%- if add_generation_prompt %}"
    "{{- '<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n' }}"
    "{%- endif %}"
)
"""Fake mode's Qwen3 non-thinking template. One user turn renders as
``<|im_start|>user\\n{content}<|im_end|>\\n<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n``."""


def _raise_exception(message: str) -> NoReturn:
    raise jinja2.TemplateError(message)


def _tojson(
    value: Any,
    ensure_ascii: bool = False,
    indent: int | None = None,
    separators: tuple[str, str] | None = None,
    sort_keys: bool = False,
) -> str:
    return json.dumps(
        value, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys
    )


class ChatTemplate:
    """A compiled chat template."""

    def __init__(self, source: str) -> None:
        env = ImmutableSandboxedEnvironment(
            trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols]
        )
        env.filters["tojson"] = _tojson
        env.globals["raise_exception"] = _raise_exception
        self.source = source
        self._template = env.from_string(source)

    @classmethod
    def from_dir(cls, directory: Path) -> "ChatTemplate":
        config = json.loads((directory / "tokenizer_config.json").read_text(encoding="utf-8"))
        source = config.get("chat_template") if isinstance(config, dict) else None
        if not isinstance(source, str):
            raise TokenizerError(f"{directory / 'tokenizer_config.json'} has no chat_template")
        return cls(source)

    def render(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        add_generation_prompt: bool,
        enable_thinking: bool,
    ) -> str:
        return self._template.render(
            messages=[dict(m) for m in messages],
            add_generation_prompt=add_generation_prompt,
            enable_thinking=enable_thinking,
        )

    def render_user_prompt(self, text: str) -> str:
        """``text`` as a single user turn, then the assistant header with thinking off."""
        return self.render(
            [{"role": "user", "content": text}], add_generation_prompt=True, enable_thinking=False
        )


def load_chat_template(stack: StackConfig, directory: Path | None = None) -> ChatTemplate:
    """The pinned chat template from ``tokenizer.local_dir`` (or ``directory``), checked first."""
    directory = stack.tokenizer_dir if directory is None else directory
    problems = check_tokenizer_dir(directory, stack.tokenizer.repo, stack.tokenizer.revision)
    if problems:
        raise TokenizerError("; ".join(problems))
    return ChatTemplate.from_dir(directory)


def template_from_env(stack: StackConfig | None = None) -> ChatTemplate:
    """The default chat template: ``FAKE_CHAT_TEMPLATE`` when ``TRIPARTITE_LLM=fake``, without
    reading ``configs/stack.yaml`` or ``tokenizer.local_dir``; otherwise the pinned template of
    ``stack`` (default ``configs/stack.yaml``), checked by ``load_chat_template``."""
    if llm_mode() == "fake":
        return ChatTemplate(FAKE_CHAT_TEMPLATE)
    return load_chat_template(load_stack() if stack is None else stack)
