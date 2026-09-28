"""The real pinned stack (local; ARCHITECTURE.md D4, D1 local gate).

Needs ``make pull-model`` and the dedicated server (``make serve-model``). Run with
``make test-local``; never in CI.
"""

import pytest
from filelock import FileLock

from tripartite.config import MODEL_LOCK_PATH, StackConfig, load_run_config, load_stack
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.llm.calibration import (
    CALIBRATION_SEED,
    COLD_PROBE_IDS,
    ProbePrompt,
    require_valid_calibration,
    run_cold_probes,
)
from tripartite.llm.chat_template import load_chat_template
from tripartite.llm.context import CONTEXT_REPORT_PATH, measure, report_json
from tripartite.llm.doctor import DoctorDeps, run_doctor
from tripartite.llm.ollama_client import DesktopApp, GenerateOptions, OllamaClient
from tripartite.llm.tokenizer import Tokenizer, check_tokenizer_dir, load_tokenizer
from tripartite.planner.prompt import PromptRenderer

pytestmark = pytest.mark.local


@pytest.fixture(scope="module")
def real_stack() -> StackConfig:
    return load_stack()


@pytest.fixture(scope="module")
def real_tokenizer(real_stack: StackConfig) -> Tokenizer:
    return load_tokenizer(real_stack)


@pytest.fixture(scope="module")
def renderer(real_stack: StackConfig) -> PromptRenderer:
    return PromptRenderer.from_config(load_run_config(), real_stack)


def test_the_tokenizer_files_are_the_pinned_ones(real_stack: StackConfig) -> None:
    tk = real_stack.tokenizer
    assert check_tokenizer_dir(real_stack.tokenizer_dir, tk.repo, tk.revision) == []


def test_chat_tokens_are_single_ids(real_tokenizer: Tokenizer) -> None:
    ids = {
        t: real_tokenizer.encode_ids(t)
        for t in ("<|endoftext|>", "<|im_start|>", "<|im_end|>", "<think>", "</think>")
    }

    assert ids == {
        "<|endoftext|>": [151643],
        "<|im_start|>": [151644],
        "<|im_end|>": [151645],
        "<think>": [151667],
        "</think>": [151668],
    }


def test_the_pinned_chat_template_renders_one_user_turn(real_stack: StackConfig) -> None:
    text = 'Given information: {"a": "ü"}\nQuery: x\nTravel Plan:'

    assert load_chat_template(real_stack).render_user_prompt(text) == (
        f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def test_the_committed_context_report_reproduces(
    real_stack: StackConfig, real_tokenizer: Tokenizer, renderer: PromptRenderer
) -> None:
    run = load_run_config()
    report = measure(
        load_planner_inputs(),
        lambda inp: renderer.render(inp).text,
        real_tokenizer,
        stack=real_stack,
        num_predict=run.generation.num_predict,
        prompt_version=run.prompt.version,
        prompt_sha256=run.prompt.sha256,
    )

    assert report.fits
    assert report_json(report) == CONTEXT_REPORT_PATH.read_text(encoding="utf-8")


def test_the_committed_calibration_is_valid(real_stack: StackConfig) -> None:
    assert require_valid_calibration(real_stack).mode in ("total", "split", "uncached_only")


def test_tokenizer_agreement(
    real_stack: StackConfig, real_tokenizer: Tokenizer, renderer: PromptRenderer
) -> None:
    """D4 step 5: re-run only the cold probes and require exact agreement (A-018)."""
    inputs = {inp.query_id: inp for inp in load_planner_inputs()}
    prompts = []
    for qid in COLD_PROBE_IDS:
        text = renderer.render(inputs[qid]).text
        prompts.append(ProbePrompt(qid, text, tuple(real_tokenizer.encode_ids(text))))
    options = GenerateOptions.production(
        real_stack, load_run_config().generation, seed=CALIBRATION_SEED, num_predict=1
    )

    MODEL_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(MODEL_LOCK_PATH, timeout=0), OllamaClient(real_stack.runtime.url) as client:
        outcome = run_cold_probes(client, real_stack, prompts, options)

    assert outcome.problems == []
    assert outcome.mismatches == []
    assert [p.prompt_eval_count for p in outcome.probes] == [len(p.ids) for p in prompts]
    assert all(p.load_ms is not None and p.load_ms > 0 for p in outcome.probes)


def test_doctor_passes_against_the_running_server(real_stack: StackConfig) -> None:
    with (
        OllamaClient(real_stack.runtime.url) as client,
        DesktopApp(real_stack.runtime.desktop_app_url) as desktop,
    ):
        checks = run_doctor(real_stack, DoctorDeps(client=client, desktop=desktop))

    assert [(c.label, c.detail) for c in checks if c.level == "fail"] == []
