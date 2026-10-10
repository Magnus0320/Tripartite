"""Response models of the API (ARCHITECTURE.md D8). They are the OpenAPI contract that
``tripartite api export-openapi`` writes to ``api-contract/openapi.json``.

A query is served as the planner may see it: ``query_id`` and ``query`` from ``PlannerInput``,
and nothing else (D3). ``reference_information`` is left out because the UI lists queries, and
no ``EvalRecord`` field is ever served; ``QueryItem`` forbids extra fields.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from tripartite.data.planner_inputs import PlannerInput


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class Health(_Response):
    """The response of GET /api/health."""

    status: Literal["ok"]
    model_reachable: bool
    model_digest_ok: bool
    evaluator_ready: bool


class QueryItem(_Response):
    """One validation query: the PlannerInput fields query_id and query only."""

    query_id: str
    query: str

    @classmethod
    def from_planner_input(cls, inp: PlannerInput) -> Self:
        return cls(query_id=inp.query_id, query=inp.query)


class QueryList(_Response):
    """The response of GET /api/queries: all 180 validation queries, in query_id order."""

    items: list[QueryItem]


class ErrorDetail(_Response):
    """An error response, for example for an unknown query_id."""

    detail: str


# --- runs (F2) -----------------------------------------------------------------------------------

RunKind = Literal["batch", "single"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]
RunStage = Literal["queued", "generating", "parsing", "evaluating", "done"]


class RunRequest(BaseModel):
    """The body of POST /api/runs: one validation query and one seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str
    seed: int = Field(default=0, ge=0)


class RunAccepted(_Response):
    """The 202 response of POST /api/runs."""

    run_id: str
    status: Literal["queued"]


class RunConflict(_Response):
    """The 409 response of POST /api/runs: a job is running, or ``runs/.model.lock`` is held.
    ``active_run_id`` is this server's running job, or null when another process holds the lock
    (for example a CLI batch run)."""

    detail: str
    active_run_id: str | None


class StageEvent(_Response):
    """The data of a ``stage`` event of GET /api/runs/{run_id}/events: the run's new stage."""

    stage: RunStage


class StreamError(_Response):
    """The data of the ``error`` event that ends the stream of a failed or interrupted run."""

    message: str


class DayPlan(_Response):
    """One day of a plan. ``attractions`` is ``attraction`` split on ``;``, trimmed, with empty
    strings and ``-`` removed, so the web client does no parsing."""

    day: int
    current_city: str
    transportation: str
    breakfast: str
    attraction: str
    attractions: list[str]
    lunch: str
    dinner: str
    accommodation: str


class Constraint(_Response):
    """One evaluator check of a plan."""

    key: str
    label: str
    group: Literal["commonsense", "hard"]
    status: Literal["pass", "fail", "not_applicable", "not_evaluated"]
    message: str | None


class Usage(_Response):
    """Tokens and latency of one (query, seed) pair, summed over its planner calls. The
    server-reported times are null when no call reported them."""

    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    load_ms: float | None
    prefill_ms: float | None
    generation_ms: float | None
    total_ms: float | None
    wall_ms: float


class ItemDetail(_Response):
    """One (query, seed) pair of a run: its plan, the evaluator's verdict and its usage."""

    query_id: str
    seed: int
    query: str
    delivered: bool
    failure_reason: str | None
    plan: list[DayPlan] | None
    constraints: list[Constraint]
    commonsense_pass: bool
    hard_pass: bool
    final_pass: bool
    usage: Usage
    raw_output: str


class ModelRef(_Response):
    tag: str
    digest: str


class Progress(_Response):
    done: int
    total: int


class MetricSummary(_Response):
    """One official metric: a rate in [0, 1] per seed, their mean, and the sample SD (null with
    fewer than two seeds)."""

    per_seed: dict[str, float]
    mean: float
    sd: float | None


class BatchSummary(_Response):
    """A batch run's progress and, once it is scored, its official metrics (empty until then)."""

    progress: Progress
    metrics: dict[str, MetricSummary]


class RunDetail(_Response):
    """The response of GET /api/runs/{run_id}. ``item`` is set for a single run once its pair is
    done; ``summary`` is set for a batch run."""

    run_id: str
    kind: RunKind
    status: RunStatus
    stage: RunStage | None
    created_at: datetime
    finished_at: datetime | None
    config_hash: str
    model: ModelRef
    prompt_version: str
    error: str | None
    item: ItemDetail | None
    summary: BatchSummary | None
