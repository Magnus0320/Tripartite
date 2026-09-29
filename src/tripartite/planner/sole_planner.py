"""The sole planner: Phase 1's one agent (ARCHITECTURE.md D4, D6, D3).

``SolePlanner.plan(inp, seed)`` renders the official prompt for one ``PlannerInput`` and calls
the model once, with D6's transport retries. It never sees an evaluator field: it takes only a
``PlannerInput`` and refuses anything else (D3). For every call it applies D4's checks:

- **Pre-flight** (§Truncation, 1): ``prompt_tokens + num_predict > num_ctx`` raises
  ``ContextOverflowError`` before anything is sent.
- **Post-check** (§Truncation, 2): the runtime's prompt count is checked against the local count
  in the calibrated mode, with ``lcp`` taken against the previous prompt this planner sent since
  its warm-up; a failure raises ``TruncationError`` or ``TokenizerMismatchError``.

``warm_up()`` sends D4's warm-up: the chat template around ``Reply with OK. nonce=<uuid4 hex>``,
with ``num_predict: 1``. It shares only the chat-template header with any planner prompt, and it
is the "previous prompt" of the first measured call.

**Retries (D6).** Transport errors (connection refused, HTTP 5xx, the 600 s timeout; the model
layer raises ``TransportError`` for all three) are retried up to ``transport_retries`` times with
the same seed, after a short pause. Model outputs are never retried because they are bad. When
every attempt fails, ``plan`` returns no text and the pair counts as not delivered
(``llm_error``, D2); a warm-up that fails every attempt raises its last error. Any other model
error (``ServerError``: a 4xx such as an unknown model, a body that is not JSON or carries an
``error`` field, a response that is not done or does not parse) is a hard error and propagates.

Every attempt, failed or not, is reported to ``on_call`` as a ``CallRecord`` before any error
propagates, so the run log holds every call (D6 "retries are logged", D7).
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from tripartite.config import Generation, StackConfig
from tripartite.data.planner_inputs import PlannerInput
from tripartite.llm.calibration import Mode, PostCheck, post_check, preflight
from tripartite.llm.errors import LLMError, TransportError
from tripartite.llm.ollama_client import GenerateOptions, GenerateRequest, GenerateResult, LLMClient
from tripartite.llm.tokenizer import Tokenizer, lcp
from tripartite.planner.prompt import PromptRenderer, RenderedPrompt, sha256_text

AGENT_ID: Final = "planner"
PLANNER_ROLE: Final = "planner"
WARMUP_ROLE: Final = "warmup"
WARMUP_TEXT: Final = "Reply with OK. nonce={nonce}"
WARMUP_PROMPT_VERSION: Final = "warmup"
WARMUP_SEED: Final = 0
WARMUP_NUM_PREDICT: Final = 1
RETRY_PAUSE_S: Final = 1.0
"""The pause before a retry after a transport error."""


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One model call (one ``llm_call`` event, D7)."""

    call_id: str
    role: str
    query_id: str | None
    """None for the warm-up."""
    seed: int | None
    """None for the warm-up."""
    attempt: int
    """0 for the first try, then 1, 2, … for each retry."""
    prompt: RenderedPrompt
    prompt_tokens: int
    """The local count of the rendered prompt (canonical, S4)."""
    request: GenerateRequest
    result: GenerateResult | None
    """None when the attempt failed."""
    error: LLMError | None
    wall_ms: float
    post_check: PostCheck | None
    """None when the attempt failed before the runtime reported anything."""


@dataclass(frozen=True, slots=True)
class PlannerOutput:
    calls: tuple[CallRecord, ...]

    @property
    def final(self) -> CallRecord:
        return self.calls[-1]

    @property
    def text(self) -> str | None:
        """The output text of the last attempt, or None when every attempt failed."""
        final = self.final
        return final.result.text if final.result is not None and final.error is None else None


OnCall = Callable[[CallRecord], None]


class SolePlanner:
    def __init__(
        self,
        *,
        client: LLMClient,
        tokenizer: Tokenizer,
        renderer: PromptRenderer,
        stack: StackConfig,
        generation: Generation,
        post_check_mode: Mode,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.client = client
        self.tokenizer = tokenizer
        self.renderer = renderer
        self.stack = stack
        self.generation = generation
        self.post_check_mode = post_check_mode
        self._sleep = sleep
        self._clock = clock
        self._previous_ids: list[int] | None = None
        """The token ids of the last prompt this planner sent (the post-check's ``lcp``)."""

    def warm_up(self, on_call: OnCall) -> CallRecord:
        """D4's warm-up call, with a fresh nonce."""
        text = self.renderer.chat.render_user_prompt(WARMUP_TEXT.format(nonce=uuid.uuid4().hex))
        prompt = RenderedPrompt(
            text=text, sha256=sha256_text(text), prompt_version=WARMUP_PROMPT_VERSION
        )
        options = GenerateOptions.production(
            self.stack, self.generation, seed=WARMUP_SEED, num_predict=WARMUP_NUM_PREDICT
        )
        output = self._call(prompt, options, WARMUP_ROLE, None, None, on_call)
        if output.final.error is not None:
            raise output.final.error
        return output.final

    def plan(self, inp: PlannerInput, seed: int, on_call: OnCall) -> PlannerOutput:
        """One planner call for ``inp`` with ``seed``, retried on transport errors only."""
        if type(inp) is not PlannerInput:
            raise TypeError(f"the planner takes a PlannerInput, got {type(inp).__name__} (D3)")
        options = GenerateOptions.production(self.stack, self.generation, seed=seed)
        return self._call(
            self.renderer.render(inp), options, PLANNER_ROLE, inp.query_id, seed, on_call
        )

    def _call(
        self,
        prompt: RenderedPrompt,
        options: GenerateOptions,
        role: str,
        query_id: str | None,
        seed: int | None,
        on_call: OnCall,
    ) -> PlannerOutput:
        ids = self.tokenizer.encode_ids(prompt.text)
        n = len(ids)
        preflight(n, options.num_predict, self.stack.model.num_ctx)
        request = GenerateRequest(self.stack.model.tag, prompt.text, options)
        calls: list[CallRecord] = []

        def record(
            result: GenerateResult | None,
            error: LLMError | None,
            wall_ms: float,
            check: PostCheck | None,
        ) -> CallRecord:
            call = CallRecord(
                call_id=uuid.uuid4().hex,
                role=role,
                query_id=query_id,
                seed=seed,
                attempt=len(calls),
                prompt=prompt,
                prompt_tokens=n,
                request=request,
                result=result,
                error=error,
                wall_ms=wall_ms,
                post_check=check,
            )
            calls.append(call)
            on_call(call)
            return call

        for attempt in range(self.generation.transport_retries + 1):
            if attempt:
                self._sleep(RETRY_PAUSE_S)
            shared = 0 if self._previous_ids is None else lcp(self._previous_ids, ids)
            start = self._clock()
            try:
                result = self.client.generate(request)
            except TransportError as exc:
                self._previous_ids = ids  # the server may have seen it
                record(None, exc, (self._clock() - start) * 1000, None)
                continue
            except LLMError as exc:
                self._previous_ids = ids
                record(None, exc, (self._clock() - start) * 1000, None)
                raise
            self._previous_ids = ids
            check = post_check(
                self.post_check_mode,
                prompt_tokens=n,
                lcp=shared,
                prompt_eval_count=result.prompt_eval_count,
                prompt_eval_cached_count=result.prompt_eval_cached_count,
            )
            record(result, None, result.wall_ms, check)
            check.raise_for_failure()
            break
        return PlannerOutput(tuple(calls))
