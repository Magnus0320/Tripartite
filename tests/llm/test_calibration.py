"""Token calibration and the per-call checks (ARCHITECTURE.md D4; A-018 to A-021)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.model.fake_ollama import FakeOllama
from tripartite.config import StackConfig
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.llm.calibration import (
    COLD_PROBE_IDS,
    CalibrationOutcome,
    CalibrationReport,
    Mode,
    ProbePrompt,
    _Warm,
    calibration_status,
    classify,
    post_check,
    preflight,
    require_valid_calibration,
    run_calibration,
    write_json,
)
from tripartite.llm.chat_template import ChatTemplate
from tripartite.llm.errors import (
    CalibrationError,
    CalibrationMissingError,
    ContextOverflowError,
    TokenizerMismatchError,
    TruncationError,
)
from tripartite.llm.ollama_client import GenerateOptions
from tripartite.llm.tokenizer import Tokenizer

INSTRUCTION = "You are a proficient planner. " * 8 + "Given information: {text}\nQuery: {query}"
OPTIONS = GenerateOptions(32768, 1, 0.7, 0.8, 20, 0.0, 1.0, 0, ("<|im_end|>", "<|endoftext|>"))


@pytest.fixture
def prompts(tokenizer: Tokenizer, chat: ChatTemplate) -> list[ProbePrompt]:
    """Production-shaped prompts for val-001 … val-009 from the synthetic set: a shared
    instruction prefix, then each query's own reference information."""
    inputs = {inp.query_id: inp for inp in load_planner_inputs()}
    out = []
    for qid in COLD_PROBE_IDS:
        inp = inputs[qid]
        text = chat.render_user_prompt(
            INSTRUCTION.format(text=inp.reference_information, query=inp.query)
        )
        out.append(ProbePrompt(qid, text, tuple(tokenizer.encode_ids(text))))
    return out


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def calibrate(
    fake: FakeOllama, stack: StackConfig, prompts: list[ProbePrompt]
) -> CalibrationOutcome:
    clock = FakeClock()
    return run_calibration(fake.client(), stack, prompts, OPTIONS, clock=clock, sleep=clock.sleep)


# --- the per-call checks ------------------------------------------------------------------------


def test_preflight() -> None:
    preflight(28672, 4096, 32768)
    with pytest.raises(ContextOverflowError, match="28673 \\+ num_predict 4096 > num_ctx 32768"):
        preflight(28673, 4096, 32768)


@pytest.mark.parametrize(
    ("mode", "count", "cached", "lcp", "ok", "bounds"),
    [
        ("total", 100, None, 0, True, (100, 100)),
        ("total", 99, None, 0, False, (100, 100)),
        ("split", 30, 70, 70, True, (100, 100)),
        ("split", 30, None, 70, False, (100, 100)),
        ("uncached_only", 30, None, 70, True, (30, 100)),
        ("uncached_only", 100, None, 70, True, (30, 100)),
        ("uncached_only", 29, None, 70, False, (30, 100)),
        ("uncached_only", None, None, 70, False, (30, 100)),
    ],
)
def test_post_check_bounds(
    mode: Mode, count: int | None, cached: int | None, lcp: int, ok: bool, bounds: tuple[int, int]
) -> None:
    check = post_check(
        mode, prompt_tokens=100, lcp=lcp, prompt_eval_count=count, prompt_eval_cached_count=cached
    )

    assert check.ok is ok
    assert (check.expected_min, check.expected_max) == bounds
    assert set(check.as_event()) == {
        "mode",
        "lcp",
        "expected_min",
        "expected_max",
        "observed",
        "ok",
    }
    if ok:
        check.raise_for_failure()
    else:
        with pytest.raises(TruncationError):
            check.raise_for_failure()


@pytest.mark.parametrize("mode", ["total", "split", "uncached_only"])
def test_post_check_above_the_local_count_is_a_tokenizer_mismatch(mode: Mode) -> None:
    check = post_check(
        mode,
        prompt_tokens=100,
        lcp=10,
        prompt_eval_count=101,
        prompt_eval_cached_count=0 if mode == "split" else None,
    )

    with pytest.raises(TokenizerMismatchError):
        check.raise_for_failure()


@pytest.mark.parametrize(
    ("first", "second", "modes"),
    [
        (_Warm(100, 100, 100, None), _Warm(90, 40, 90, None), ["total"]),
        (_Warm(100, 100, 1, 99), _Warm(90, 40, 50, 40), ["split"]),
        (_Warm(100, 100, 1, None), _Warm(90, 40, 50, None), ["uncached_only"]),
        (_Warm(100, 100, 100, 0), _Warm(90, 40, 90, 0), ["total", "split"]),
        (_Warm(100, 100, 100, None), _Warm(90, 40, 50, None), []),
        (_Warm(100, 100, 1, None), _Warm(90, 40, 49, None), []),
        (_Warm(100, 100, None, None), _Warm(90, 40, 90, None), []),
    ],
)
def test_classify(first: _Warm, second: _Warm, modes: list[str]) -> None:
    assert classify(first, second) == modes


# --- run_calibration ----------------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "warm"), [("total", 2), ("split", 2), ("uncached_only", 3)])
def test_each_mode_is_classified(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt], mode: str, warm: int
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer, mode=mode)

    outcome = calibrate(fake, stack, prompts)

    assert outcome.ok, outcome.problems + outcome.mismatches
    assert outcome.mode == mode
    kinds = [p.kind for p in outcome.probes]
    assert kinds == ["cold"] * 9 + ["warm"] * warm
    cold = outcome.probes[:9]
    assert [p.query_id for p in cold] == list(COLD_PROBE_IDS)
    assert all(p.prompt_eval_count == p.prompt_tokens and p.lcp is None for p in cold)
    assert all(p.load_ms == 1500.0 for p in cold)
    assert [p.query_id for p in outcome.probes[9:]] == ["val-009", "val-001", "val-009"][:warm]
    identical, shared = outcome.probes[9], outcome.probes[10]
    assert identical.lcp == identical.prompt_tokens
    assert 0 < shared.lcp < shared.prompt_tokens  # the instruction prefix only


def test_cold_probes_unload_and_wait_first(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer)

    calibrate(fake, stack, prompts)

    calls = [(m, p, json.loads(b).get("keep_alive") if b else None) for m, p, b in fake.requests]
    first = calls.index(("POST", "/api/generate", -1))
    assert calls[:first] == [("POST", "/api/generate", 0), ("GET", "/api/ps", None)]


def test_a_tokenizer_mismatch_fails_before_the_warm_probes(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer, token_offset=1)

    outcome = calibrate(fake, stack, prompts)

    assert not outcome.ok
    assert len(outcome.mismatches) == 9
    assert "cold probe val-001: prompt_eval_count" in outcome.mismatches[0]
    assert [p.kind for p in outcome.probes] == ["cold"] * 9
    with pytest.raises(TokenizerMismatchError, match="A-018"):
        outcome.raise_for_failure()


def test_a_cold_probe_without_a_fresh_load_fails(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer, load_ns=0)

    outcome = calibrate(fake, stack, prompts)

    assert not outcome.ok
    assert "load_duration is 0.0, not > 0" in outcome.problems[0]
    with pytest.raises(CalibrationError, match="A-021"):
        outcome.raise_for_failure()


def test_an_unload_that_never_happens_times_out(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer, unload_works=False)
    fake.loaded_ctx = 32768

    outcome = calibrate(fake, stack, prompts)

    assert outcome.probes == []
    assert "still loaded 60 s after keep_alive: 0 (A-021)" in outcome.problems[0]


def test_a_cache_that_keeps_older_prompts_fails_a020(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = FakeOllama.for_stack(stack, tokenizer, keeps_older=True)

    outcome = calibrate(fake, stack, prompts)

    assert outcome.mode is None
    assert len(outcome.probes) == 12
    assert "A-020 fails" in outcome.problems[0]


class Inconsistent(FakeOllama):
    """Counts the whole prompt on warm probe (i) but only the uncached part on (ii)."""

    def _generate(self, body: dict[str, Any]) -> httpx.Response:
        self.mode = "total" if self.generated < 10 else "uncached_only"
        return super()._generate(body)


def test_an_unclassifiable_runtime_is_an_architecture_question(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    fake = Inconsistent.for_stack(stack, tokenizer)

    outcome = calibrate(fake, stack, prompts)

    assert outcome.mode is None
    assert "an architecture question" in outcome.problems[-1]


def test_the_probe_ids_are_fixed(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    with pytest.raises(ValueError, match="val-001"):
        calibrate(FakeOllama.for_stack(stack, tokenizer), stack, prompts[::-1])


# --- the report and its validity ---------------------------------------------------------------


def good_report(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> CalibrationReport:
    outcome = calibrate(FakeOllama.for_stack(stack, tokenizer), stack, prompts)
    return outcome.report(stack, "0.33.2", datetime(2026, 9, 28, 5, 0, tzinfo=UTC))


def test_report_fields(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt], tmp_path: Path
) -> None:
    report = good_report(tokenizer, stack, prompts)
    path = tmp_path / "token_calibration.json"
    write_json(report, path)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert list(data) == [
        "calibrated_at",
        "ollama_version",
        "model_tag",
        "model_digest",
        "tokenizer_repo",
        "tokenizer_revision",
        "num_ctx",
        "mode",
        "probes",
    ]
    assert data["calibrated_at"] == "2026-09-28T05:00:00Z"
    assert (data["model_digest"], data["num_ctx"], data["mode"]) == (
        stack.model.digest,
        32768,
        "uncached_only",
    )
    assert list(data["probes"][0]) == [
        "kind",
        "query_id",
        "prompt_tokens",
        "lcp",
        "prompt_eval_count",
        "prompt_eval_cached_count",
        "load_ms",
    ]
    assert calibration_status(stack, path).status == "valid"
    assert require_valid_calibration(stack, path) == report


def test_a_failed_outcome_has_no_report(
    tokenizer: Tokenizer, stack: StackConfig, prompts: list[ProbePrompt]
) -> None:
    outcome = calibrate(FakeOllama.for_stack(stack, tokenizer, token_offset=-1), stack, prompts)

    with pytest.raises(TokenizerMismatchError):
        outcome.report(stack, "0.33.2", datetime.now(UTC))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ollama_version", "0.33.1"),
        ("model_digest", "sha256:500a1f067a9f" + "0" * 52),
        ("tokenizer_revision", "0" * 40),
        ("num_ctx", 16384),
    ],
)
def test_a_report_for_other_pins_is_stale(
    tokenizer: Tokenizer,
    stack: StackConfig,
    prompts: list[ProbePrompt],
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    path = tmp_path / "token_calibration.json"
    write_json(good_report(tokenizer, stack, prompts).model_copy(update={field: value}), path)

    status = calibration_status(stack, path)

    assert status.status == "stale"
    assert field in status.detail
    with pytest.raises(CalibrationMissingError, match="stale"):
        require_valid_calibration(stack, path)


def test_missing_and_invalid_reports(stack: StackConfig, tmp_path: Path) -> None:
    path = tmp_path / "token_calibration.json"
    assert calibration_status(stack, path).status == "missing"
    with pytest.raises(CalibrationMissingError, match="missing"):
        require_valid_calibration(stack, path)

    path.write_text('{"mode": "total"}', encoding="utf-8")
    assert calibration_status(stack, path).status == "invalid"
    with pytest.raises(CalibrationMissingError, match="invalid"):
        require_valid_calibration(stack, path)
