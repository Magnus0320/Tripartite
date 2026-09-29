"""Token calibration and the per-call checks it drives (ARCHITECTURE.md D4; A-018 to A-021).

Every planner prompt starts with the same chat header and official instruction, so later calls
can hit Ollama's prompt cache, and ``prompt_eval_count`` may leave cached tokens out. The
calibration therefore classifies how the pinned runtime reports prompt tokens, and the per-call
post-check uses that mode:

- **Cold probes** (uncached by construction): for ``val-001`` … ``val-009``, unload the model
  (``keep_alive: 0``), wait until ``/api/ps`` no longer lists it (60 s), send the production
  prompt with ``num_predict: 1``, and require ``load_duration > 0`` (A-021). Tokenizer agreement:
  ``prompt_eval_count == prompt_tokens`` exactly, on all nine (A-018).
- **Warm probes** (A-019), straight after the ninth: (i) the same prompt again, (ii) ``val-001``,
  which shares only the instruction prefix. ``lcp`` is the common token-id prefix with the prompt
  sent just before. Exactly one mode must fit both: ``total``, ``split`` or ``uncached_only``.
  In ``uncached_only``, (iii) re-sends ``val-009`` and must satisfy
  ``prompt_eval_count >= prompt_tokens - lcp`` (A-020). Anything else fails the calibration and
  is an architecture question; no rule is improvised here.

``reports/token_calibration.json`` is valid only while its Ollama version, model digest,
tokenizer revision and ``num_ctx`` equal ``configs/stack.yaml``. Real-model runs refuse to start
without a valid one (``require_valid_calibration``); the fake client needs none. A report whose
tokenizer is fake mode's ``fake-bytes@v1`` is always stale, whatever the mode (FU-25).
"""

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, ValidationError

from tripartite.config import REPO_ROOT, StackConfig
from tripartite.llm.errors import (
    CalibrationError,
    CalibrationMissingError,
    ContextOverflowError,
    LLMError,
    TokenizerMismatchError,
    TruncationError,
)
from tripartite.llm.fake_client import FAKE_TOKENIZER_ID
from tripartite.llm.ollama_client import GenerateOptions, GenerateRequest, OllamaClient
from tripartite.llm.tokenizer import lcp

CALIBRATION_REPORT_PATH: Final = REPO_ROOT / "reports" / "token_calibration.json"
COLD_PROBE_IDS: Final = tuple(f"val-{i:03d}" for i in range(1, 10))
"""Fixed ids, so the calibration does not depend on ``configs/smoke.yaml`` (D4)."""
CALIBRATION_SEED: Final = 0
UNLOAD_TIMEOUT_S: Final = 60.0
UNLOAD_POLL_S: Final = 0.25

Mode = Literal["total", "split", "uncached_only"]
MODES: Final[tuple[Mode, ...]] = ("total", "split", "uncached_only")


# --- the per-call checks (D4 §Truncation) ---------------------------------------------------


def preflight(prompt_tokens: int, num_predict: int, num_ctx: int) -> None:
    """(1) Refuse a call whose prompt and output cannot both fit in the context."""
    if prompt_tokens + num_predict > num_ctx:
        raise ContextOverflowError(
            f"prompt_tokens {prompt_tokens} + num_predict {num_predict} > num_ctx {num_ctx}"
        )


@dataclass(frozen=True, slots=True)
class PostCheck:
    """(2) The ``post_check`` field of an ``llm_call`` event (D4)."""

    mode: Mode
    lcp: int
    expected_min: int
    expected_max: int
    observed: int
    ok: bool

    def as_event(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "lcp": self.lcp,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "observed": self.observed,
            "ok": self.ok,
        }

    def raise_for_failure(self) -> None:
        if self.observed > self.expected_max:
            raise TokenizerMismatchError(
                f"post-check ({self.mode}): the runtime reported {self.observed} prompt tokens, "
                f"more than the local count {self.expected_max}"
            )
        if self.observed < self.expected_min:
            raise TruncationError(
                f"post-check ({self.mode}): the runtime reported {self.observed} prompt tokens, "
                f"below the lower bound {self.expected_min} (lcp {self.lcp})"
            )


def post_check(
    mode: Mode,
    *,
    prompt_tokens: int,
    lcp: int,
    prompt_eval_count: int | None,
    prompt_eval_cached_count: int | None,
) -> PostCheck:
    """Check one real-model call against the calibrated mode. ``lcp`` is the token prefix this
    call's prompt shares with the previous prompt this process sent since its warm-up.

    A count the runtime omitted is taken as 0: Ollama leaves zero counts out of its JSON, and a
    0 fails loudly as truncation rather than passing silently.
    """
    count = prompt_eval_count or 0
    if mode == "split":
        observed = count + (prompt_eval_cached_count or 0)
        low = high = prompt_tokens
    elif mode == "total":
        observed = count
        low = high = prompt_tokens
    else:
        observed = count
        low, high = prompt_tokens - lcp, prompt_tokens
    return PostCheck(mode, lcp, low, high, observed, low <= observed <= high)


# --- reports/token_calibration.json ---------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Probe(_Frozen):
    kind: Literal["cold", "warm"]
    query_id: str
    prompt_tokens: NonNegativeInt
    lcp: NonNegativeInt | None
    """Null for cold probes: the model was just loaded, so nothing was cached."""
    prompt_eval_count: NonNegativeInt | None
    prompt_eval_cached_count: NonNegativeInt | None
    load_ms: float | None


class CalibrationReport(_Frozen):
    calibrated_at: str
    ollama_version: str
    model_tag: str
    model_digest: str
    tokenizer_repo: str
    tokenizer_revision: str
    num_ctx: int
    mode: Mode
    probes: list[Probe]


def write_json(data: BaseModel, path: Path) -> None:
    """Write ``data`` as indented JSON with a final newline, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


Status = Literal["missing", "valid", "stale", "invalid"]


def fake_tokenizer_detail(tokenizer_repo: str, tokenizer_revision: str) -> str | None:
    """Why a report counted with fake mode's tokenizer is stale, or None if it was not (FU-25)."""
    if f"{tokenizer_repo}@{tokenizer_revision}" != FAKE_TOKENIZER_ID:
        return None
    return (
        f"written with the fake tokenizer {FAKE_TOKENIZER_ID} (TRIPARTITE_LLM=fake), so its "
        "counts are not Qwen counts; re-run `make measure-context` against the real stack"
    )


@dataclass(frozen=True, slots=True)
class CalibrationStatus:
    status: Status
    detail: str
    report: CalibrationReport | None = None


def calibration_status(
    stack: StackConfig, path: Path = CALIBRATION_REPORT_PATH
) -> CalibrationStatus:
    """``missing``, ``valid``, ``stale`` (pins changed since, or written with the fake tokenizer),
    or ``invalid`` (unreadable)."""
    try:
        report = CalibrationReport.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return CalibrationStatus("missing", "run `make measure-context` with the server up")
    except ValidationError as exc:
        return CalibrationStatus("invalid", f"{path.name} does not validate: {exc}")
    if fake := fake_tokenizer_detail(report.tokenizer_repo, report.tokenizer_revision):
        return CalibrationStatus("stale", fake, report)
    changed = [
        f"{name} {have!r} != {want!r}"
        for name, have, want in (
            ("ollama_version", report.ollama_version, stack.runtime.version),
            ("model_digest", report.model_digest, stack.model.digest),
            ("tokenizer_revision", report.tokenizer_revision, stack.tokenizer.revision),
            ("num_ctx", report.num_ctx, stack.model.num_ctx),
        )
        if have != want
    ]
    if changed:
        return CalibrationStatus(
            "stale", "; ".join(changed) + "; re-run `make measure-context`", report
        )
    return CalibrationStatus("valid", f"mode {report.mode}, {report.calibrated_at}", report)


def require_valid_calibration(
    stack: StackConfig, path: Path = CALIBRATION_REPORT_PATH
) -> CalibrationReport:
    """The valid calibration, or ``CalibrationMissingError`` before any model call (D4)."""
    status = calibration_status(stack, path)
    if status.status != "valid" or status.report is None:
        raise CalibrationMissingError(f"{path.name} is {status.status}: {status.detail}")
    return status.report


# --- the calibration itself -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProbePrompt:
    query_id: str
    text: str
    """The exact production prompt bytes (chat template included)."""
    ids: tuple[int, ...]
    """Its local token ids."""


@dataclass(frozen=True, slots=True)
class _Warm:
    prompt_tokens: int
    lcp: int
    count: int | None
    cached: int | None


def classify(first: _Warm, second: _Warm) -> list[Mode]:
    """Every mode whose rule holds on both warm probes (D4 step 3)."""

    def fits(mode: Mode, w: _Warm) -> bool:
        if w.count is None:
            return False
        if mode == "total":
            return w.count == w.prompt_tokens
        if mode == "split":
            return w.cached is not None and w.count + w.cached == w.prompt_tokens
        return w.cached is None and w.prompt_tokens - w.lcp <= w.count < w.prompt_tokens

    return [m for m in MODES if fits(m, first) and fits(m, second)]


@dataclass
class CalibrationOutcome:
    probes: list[Probe] = field(default_factory=list)
    mode: Mode | None = None
    mismatches: list[str] = field(default_factory=list)
    """Cold probes whose count differs from the local tokenizer (A-018)."""
    problems: list[str] = field(default_factory=list)
    """Every other failure."""

    @property
    def ok(self) -> bool:
        return self.mode is not None and not self.mismatches and not self.problems

    def raise_for_failure(self) -> None:
        if self.mismatches:
            raise TokenizerMismatchError("; ".join(self.mismatches))
        if self.problems or self.mode is None:
            raise CalibrationError("; ".join(self.problems) or "no mode was classified")

    def report(self, stack: StackConfig, ollama_version: str, now: datetime) -> CalibrationReport:
        self.raise_for_failure()
        assert self.mode is not None
        return CalibrationReport(
            calibrated_at=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ollama_version=ollama_version,
            model_tag=stack.model.tag,
            model_digest=stack.model.digest,
            tokenizer_repo=stack.tokenizer.repo,
            tokenizer_revision=stack.tokenizer.revision,
            num_ctx=stack.model.num_ctx,
            mode=self.mode,
            probes=self.probes,
        )


def _is_loaded(client: OllamaClient, stack: StackConfig) -> bool:
    return any(m.name == stack.model.tag or m.digest == stack.digest_hex for m in client.ps())


def unload_and_wait(
    client: OllamaClient,
    stack: StackConfig,
    *,
    timeout_s: float = UNLOAD_TIMEOUT_S,
    poll_s: float = UNLOAD_POLL_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Unload the model and wait until ``/api/ps`` no longer lists it (A-021)."""
    client.unload(stack.model.tag)
    deadline = clock() + timeout_s
    while _is_loaded(client, stack):
        if clock() >= deadline:
            raise CalibrationError(
                f"{stack.model.tag} was still loaded {timeout_s:g} s after keep_alive: 0 (A-021)"
            )
        sleep(poll_s)


def _sender(
    client: OllamaClient, stack: StackConfig, options: GenerateOptions
) -> Callable[[ProbePrompt], tuple[int | None, int | None, float | None]]:
    def send(prompt: ProbePrompt) -> tuple[int | None, int | None, float | None]:
        r = client.generate(GenerateRequest(stack.model.tag, prompt.text, options))
        return r.prompt_eval_count, r.prompt_eval_cached_count, r.load_ms

    return send


def run_cold_probes(
    client: OllamaClient,
    stack: StackConfig,
    prompts: Sequence[ProbePrompt],
    options: GenerateOptions,
    *,
    unload_timeout_s: float = UNLOAD_TIMEOUT_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CalibrationOutcome:
    """Step 2 alone: the nine cold probes and the tokenizer agreement (A-018, A-021).
    ``make test-local`` re-runs exactly this (``test_tokenizer_agreement``, D4 step 5).

    ``prompts`` are the production prompts of ``COLD_PROBE_IDS``, in order; ``options`` are the
    production options with ``num_predict: 1``.
    """
    if tuple(p.query_id for p in prompts) != COLD_PROBE_IDS:
        raise ValueError(f"the probes must be {COLD_PROBE_IDS}, in order")
    outcome = CalibrationOutcome()
    send = _sender(client, stack, options)
    for prompt in prompts:
        try:
            unload_and_wait(client, stack, timeout_s=unload_timeout_s, clock=clock, sleep=sleep)
            count, cached, load_ms = send(prompt)
        except LLMError as exc:
            outcome.problems.append(f"cold probe {prompt.query_id}: {type(exc).__name__}: {exc}")
            return outcome
        n = len(prompt.ids)
        outcome.probes.append(
            Probe(
                kind="cold",
                query_id=prompt.query_id,
                prompt_tokens=n,
                lcp=None,
                prompt_eval_count=count,
                prompt_eval_cached_count=cached,
                load_ms=load_ms,
            )
        )
        if load_ms is None or load_ms <= 0:
            outcome.problems.append(
                f"cold probe {prompt.query_id}: load_duration is {load_ms}, not > 0, so the "
                "model was not freshly loaded (A-021)"
            )
        if count != n:
            outcome.mismatches.append(
                f"cold probe {prompt.query_id}: prompt_eval_count {count} != local "
                f"prompt_tokens {n} (A-018)"
            )
    return outcome


def run_calibration(
    client: OllamaClient,
    stack: StackConfig,
    prompts: Sequence[ProbePrompt],
    options: GenerateOptions,
    *,
    unload_timeout_s: float = UNLOAD_TIMEOUT_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CalibrationOutcome:
    """Run the cold probes, then (if they all agree) the warm probes, and classify the mode.
    Arguments as for ``run_cold_probes``."""
    outcome = run_cold_probes(
        client,
        stack,
        prompts,
        options,
        unload_timeout_s=unload_timeout_s,
        clock=clock,
        sleep=sleep,
    )
    if outcome.mismatches or outcome.problems:
        return outcome
    send = _sender(client, stack, options)

    last, first = prompts[-1], prompts[0]
    warm: list[_Warm] = []
    try:
        for prompt, previous in ((last, last), (first, last)):
            count, cached, load_ms = send(prompt)
            w = _Warm(len(prompt.ids), lcp(previous.ids, prompt.ids), count, cached)
            warm.append(w)
            outcome.probes.append(
                Probe(
                    kind="warm",
                    query_id=prompt.query_id,
                    prompt_tokens=w.prompt_tokens,
                    lcp=w.lcp,
                    prompt_eval_count=count,
                    prompt_eval_cached_count=cached,
                    load_ms=load_ms,
                )
            )
    except LLMError as exc:
        outcome.problems.append(f"warm probe: {type(exc).__name__}: {exc}")
        return outcome

    modes = classify(warm[0], warm[1])
    if len(modes) != 1:
        outcome.problems.append(
            f"the warm probes fit {modes or 'no mode'}, not exactly one of {list(MODES)}: "
            "an architecture question (D4 step 3)"
        )
        return outcome
    if modes[0] == "uncached_only":
        try:
            count, cached, load_ms = send(last)
        except LLMError as exc:
            outcome.problems.append(f"warm probe (iii): {type(exc).__name__}: {exc}")
            return outcome
        n, shared = len(last.ids), lcp(first.ids, last.ids)
        outcome.probes.append(
            Probe(
                kind="warm",
                query_id=last.query_id,
                prompt_tokens=n,
                lcp=shared,
                prompt_eval_count=count,
                prompt_eval_cached_count=cached,
                load_ms=load_ms,
            )
        )
        if count is None or count < n - shared:
            outcome.problems.append(
                f"warm probe (iii) {last.query_id}: prompt_eval_count {count} < prompt_tokens "
                f"{n} - lcp {shared}, so the cache kept an older prompt (A-020 fails)"
            )
            return outcome
    outcome.mode = modes[0]
    return outcome
