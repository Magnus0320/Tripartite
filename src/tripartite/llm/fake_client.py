"""The fake LLM client (``TRIPARTITE_LLM=fake``; ARCHITECTURE.md D1, D3, D4).

A real backend code path for CI and web development, not a mock. It records every request body
byte for byte, exactly as ``build_generate_body`` produces it for the real server, so the leak
test (D3 test 3) can search what the server would have received. It reports
``prompt_eval_count == prompt_tokens`` (the local count), so the post-check runs in mode
``total`` and no calibration file is needed (D4). Output is at most ``num_predict`` tokens, and
``done_reason`` is ``"length"`` when it was cut.
"""

from collections.abc import Callable
from typing import Final

from tripartite.config import StackConfig
from tripartite.llm.ollama_client import (
    GenerateRequest,
    GenerateResult,
    LLMClient,
    OllamaClient,
    build_generate_body,
    llm_mode,
)
from tripartite.llm.tokenizer import Tokenizer

FAKE_OUTPUT: Final = (
    "Day 1:\n"
    "Current City: -\n"
    "Transportation: -\n"
    "Breakfast: -\n"
    "Attraction: -\n"
    "Lunch: -\n"
    "Dinner: -\n"
    "Accommodation: -"
)
"""The default reply: one day in the official line format, every field ``-``."""
FAKE_LOAD_MS: Final = 0.0
FAKE_MS_PER_TOKEN: Final = 0.01


class FakeClient:
    def __init__(
        self, tokenizer: Tokenizer, respond: Callable[[GenerateRequest], str] | None = None
    ) -> None:
        self._tokenizer = tokenizer
        self._respond = respond or (lambda _request: FAKE_OUTPUT)
        self.requests: list[bytes] = []
        """Every request body, byte for byte, in call order."""

    def generate(self, request: GenerateRequest) -> GenerateResult:
        self.requests.append(build_generate_body(request))
        prompt_tokens = self._tokenizer.count(request.prompt)
        ids = self._tokenizer.encode_ids(self._respond(request))
        done_reason = "stop"
        if len(ids) > request.options.num_predict:
            ids = ids[: request.options.num_predict]
            done_reason = "length"
        prefill_ms = prompt_tokens * FAKE_MS_PER_TOKEN
        generation_ms = len(ids) * FAKE_MS_PER_TOKEN
        total_ms = FAKE_LOAD_MS + prefill_ms + generation_ms
        return GenerateResult(
            text=self._tokenizer.decode(ids),
            done_reason=done_reason,
            prompt_eval_count=prompt_tokens,
            prompt_eval_cached_count=None,
            eval_count=len(ids),
            load_ms=FAKE_LOAD_MS,
            prefill_ms=prefill_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            wall_ms=total_ms,
        )


def make_client(stack: StackConfig, tokenizer: Tokenizer) -> LLMClient:
    """The fake client when ``TRIPARTITE_LLM=fake``, else the dedicated server's client."""
    if llm_mode() == "fake":
        return FakeClient(tokenizer)
    return OllamaClient(stack.runtime.url)
