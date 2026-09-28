"""The official sole-planning "direct" prompt, version ``sp-direct-v1`` (ARCHITECTURE.md D6, D3).

``prompts/sole_planning_direct_v1.txt`` is ``PLANNER_INSTRUCTION`` from the vendored
``agents/prompts.py``, byte for byte, and its sha256 is recorded in the run config. A rendered
prompt is ``chat_template(PLANNER_INSTRUCTION.format(text=reference_information, query=query))``:
one user turn, no system message, thinking off (D4, D6). It is a pure function of the two
fields the planner may see (D3), and ``render_prompt`` refuses anything but a ``PlannerInput``.

At M3 this module exists only so that ``measure-context`` and ``calibrate`` can count and probe
the exact production bytes; no plan is generated from it before A-009 is settled (D9 note).
"""

import functools
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from tripartite.config import REPO_ROOT, RunConfig, StackConfig, load_run_config, load_stack
from tripartite.data.planner_inputs import PlannerInput
from tripartite.llm.chat_template import ChatTemplate, load_chat_template

PROMPT_VERSION: Final = "sp-direct-v1"
PROMPT_PATH: Final = REPO_ROOT / "prompts" / "sole_planning_direct_v1.txt"


class PromptError(RuntimeError):
    """The prompt file differs from the sha256 recorded in the run config."""


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    text: str
    """The raw prompt sent with ``raw: true``, chat template included."""
    sha256: str
    """sha256 of ``text`` in UTF-8 (the ``blobs/`` key, D7)."""
    prompt_version: str


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_template(path: Path, expected_sha256: str) -> str:
    """The prompt file's text, refusing any byte change against the recorded sha256 (D6)."""
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise PromptError(
            f"{path.name}: sha256 {actual}, but the run config records {expected_sha256}; "
            "any byte change is a new prompt version (D6)"
        )
    return data.decode("utf-8")


def _require_planner_input(inp: object) -> None:
    if type(inp) is not PlannerInput:
        raise TypeError(f"render_prompt takes a PlannerInput, got {type(inp).__name__} (D3)")


class PromptRenderer:
    """Renders planner prompts from one template and one chat template."""

    def __init__(
        self, template: str, chat: ChatTemplate, prompt_version: str = PROMPT_VERSION
    ) -> None:
        self.template = template
        self.chat = chat
        self.prompt_version = prompt_version
        self.template_sha256 = sha256_text(template)

    @classmethod
    def from_config(
        cls, run: RunConfig, stack: StackConfig, *, tokenizer_dir: Path | None = None
    ) -> Self:
        template = load_template(run.prompt_path, run.prompt.sha256)
        return cls(template, load_chat_template(stack, tokenizer_dir), run.prompt.version)

    def render(self, inp: PlannerInput) -> RenderedPrompt:
        _require_planner_input(inp)
        body = self.template.format(text=inp.reference_information, query=inp.query)
        text = self.chat.render_user_prompt(body)
        return RenderedPrompt(
            text=text, sha256=sha256_text(text), prompt_version=self.prompt_version
        )


@functools.cache
def default_renderer() -> PromptRenderer:
    """The production renderer: ``configs/baseline.yaml``'s prompt, the pinned chat template."""
    run = load_run_config()
    return PromptRenderer.from_config(run, load_stack(run.stack_path))


def render_prompt(inp: PlannerInput) -> RenderedPrompt:
    """The production prompt for ``inp`` (D3). Raises ``TypeError`` unless
    ``type(inp) is PlannerInput``, before anything is loaded."""
    _require_planner_input(inp)
    return default_renderer().render(inp)
