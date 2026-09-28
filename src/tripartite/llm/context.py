"""Context measurement, the first step of ``make measure-context`` (ARCHITECTURE.md D4; A-006).

Tokenizer only, no server. For each of the 180 validation queries it counts ``ref_tokens`` (the
reference information alone) and ``prompt_tokens`` (the full rendered raw prompt, exactly the
bytes a real call sends), and writes ``reports/context_report.json``. The measurement is a
**gate**, not an input: ``num_ctx`` is a pin, and the step fails when
``max(prompt_tokens) + num_predict + 256 > num_ctx``. Then the run stops and an architecture
question is raised (YaRN is not approved).

``p95`` is the nearest-rank percentile, index ``ceil(0.95 n) - 1`` of the sorted values (D7).
The report also names the prompt version and sha256 it was measured with, so a later prompt
change (A-009) cannot reuse it unnoticed.
"""

import json
import math
import statistics
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, NonNegativeInt, ValidationError

from tripartite.config import REPO_ROOT, StackConfig
from tripartite.data.planner_inputs import PlannerInput
from tripartite.llm.tokenizer import Tokenizer

CONTEXT_REPORT_PATH: Final = REPO_ROOT / "reports" / "context_report.json"
SAFETY_MARGIN_TOKENS: Final = 256
SUMMARY_FIELDS: Final = ("ref_chars", "ref_tokens", "prompt_tokens")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QueryCount(_Frozen):
    query_id: str
    ref_chars: NonNegativeInt
    ref_tokens: NonNegativeInt
    prompt_tokens: NonNegativeInt


class Summary(_Frozen):
    min: int
    median: float
    p95: int
    max: int


class ContextReport(_Frozen):
    tokenizer: str
    revision: str
    num_ctx: int
    num_predict: int
    prompt_version: str
    prompt_sha256: str
    per_query: list[QueryCount]
    summary: dict[str, Summary]
    fits: bool
    headroom_tokens: int
    """``num_ctx - num_predict - 256 - max(prompt_tokens)``; negative when it does not fit."""


def nearest_rank_p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def summarize(values: Sequence[int]) -> Summary:
    if not values:
        raise ValueError("nothing to summarize")
    return Summary(
        min=min(values),
        median=float(statistics.median(values)),
        p95=nearest_rank_p95(values),
        max=max(values),
    )


def prompt_budget(num_ctx: int, num_predict: int) -> int:
    """The largest prompt that fits: ``num_ctx - num_predict - 256`` (28416 for Phase 1)."""
    return num_ctx - num_predict - SAFETY_MARGIN_TOKENS


def measure(
    inputs: Sequence[PlannerInput],
    render: Callable[[PlannerInput], str],
    tokenizer: Tokenizer,
    *,
    stack: StackConfig,
    num_predict: int,
    prompt_version: str,
    prompt_sha256: str,
) -> ContextReport:
    per_query = [
        QueryCount(
            query_id=inp.query_id,
            ref_chars=len(inp.reference_information),
            ref_tokens=tokenizer.count(inp.reference_information),
            prompt_tokens=tokenizer.count(render(inp)),
        )
        for inp in inputs
    ]
    summary = {name: summarize([getattr(q, name) for q in per_query]) for name in SUMMARY_FIELDS}
    headroom = prompt_budget(stack.model.num_ctx, num_predict) - summary["prompt_tokens"].max
    # The tokenizer that counted, not the pin: a fake-mode report says fake-bytes@v1 (D4).
    repo, _, revision = tokenizer.id.rpartition("@")
    return ContextReport(
        tokenizer=repo,
        revision=revision,
        num_ctx=stack.model.num_ctx,
        num_predict=num_predict,
        prompt_version=prompt_version,
        prompt_sha256=prompt_sha256,
        per_query=per_query,
        summary=summary,
        fits=headroom >= 0,
        headroom_tokens=headroom,
    )


def load_context_report(path: Path = CONTEXT_REPORT_PATH) -> ContextReport | None:
    """The report, or None if it is missing. An unreadable report raises ``ValueError``."""
    try:
        return ContextReport.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except ValidationError as exc:
        raise ValueError(f"{path.name} does not validate: {exc}") from None


def report_json(report: ContextReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2) + "\n"
