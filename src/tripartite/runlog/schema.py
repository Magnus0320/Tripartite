"""Run-log schemas (ARCHITECTURE.md D7).

Every line of ``runs/<run_id>/events.jsonl`` is one event: the envelope (``schema_version``,
``event_id``, ``seq``, ``ts``, ``run_id``, ``event_type``) followed by the payload of its
event type. Readers ignore unknown event types and unknown fields, so every model here keeps
extra fields instead of rejecting them (for example the ``post_check`` field that D4 adds to
``llm_call``).

Writers build a payload model (``RunStart``, ``LlmCall``, ...) and pass it to
``RunLogWriter``, which adds the envelope. Readers get the flat ``*Event`` models, which carry
both.

The other files of a run directory have models here too: ``RunManifest`` (``manifest.json``),
``MetricsSeed`` (``metrics_seed{n}.json``) and ``Metrics`` (``metrics.json``).

The JSON Schema is committed next to this file as ``schema.json``. Its root validates one
``events.jsonl`` line; ``RunManifest``, ``MetricsSeed`` and ``Metrics`` are under ``$defs``.
Regenerate it after any change here::

    uv run python -m tripartite.runlog.schema > src/tripartite/runlog/schema.json
"""

import json
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self, get_args

from pydantic import (
    UUID4,
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    field_serializer,
    model_validator,
)

SCHEMA_VERSION: Final = 1
SCHEMA_JSON_PATH: Final = Path(__file__).with_name("schema.json")

# [0-9] rather than \d: the validator's regex engine treats \d as any Unicode digit.
RUN_ID_PATTERN: Final = r"^[0-9]{8}T[0-9]{6}Z-(batch|single)-[0-9a-f]{8}-[0-9a-f]{4}$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be in UTC")
    return value.astimezone(UTC)


RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
Sha256 = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]
"""RFC 3339, UTC; serialized with a ``Z`` suffix."""
Rate = Annotated[float, Field(ge=0.0, le=1.0)]
"""A rate in [0, 1]. Rates are never percentages in stored files (D7)."""

RunKind = Literal["batch", "single"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]
RunStage = Literal["queued", "generating", "parsing", "evaluating", "done"]

OfficialMetric = Literal[
    "Delivery Rate",
    "Commonsense Constraint Micro Pass Rate",
    "Commonsense Constraint Macro Pass Rate",
    "Hard Constraint Micro Pass Rate",
    "Hard Constraint Macro Pass Rate",
    "Final Pass Rate",
]
"""The six keys of the official ``eval_score`` result, verbatim (eval.py at e52c87f4)."""
OFFICIAL_METRIC_KEYS: Final[tuple[str, ...]] = get_args(OfficialMetric)

RUN_END_COUNT_KEYS: Final = (
    "queries",
    "seeds",
    "pairs_total",
    "pairs_done",
    "delivered",
    "llm_calls",
    "errors",
)
"""Keys that ``run_end.counts`` MUST contain at least (D7). Enforced by ``RunEnd`` (v0.5, AQ6)."""

ConstraintResult = tuple[bool | None, str | None]
"""One evaluator check as ``[value, message]``; a value of None means not applicable (A-014)."""


def _all_official_keys[V](value: dict[OfficialMetric, V]) -> dict[OfficialMetric, V]:
    missing = [key for key in OFFICIAL_METRIC_KEYS if key not in value]
    if missing:
        raise ValueError(f"missing official metric keys: {missing}")
    return value


def _all_run_end_count_keys(value: dict[str, int]) -> dict[str, int]:
    missing = [key for key in RUN_END_COUNT_KEYS if key not in value]
    if missing:
        raise ValueError(f"missing run_end count keys: {missing}")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, protected_namespaces=())


# --- nested values ------------------------------------------------------------------------


class ModelInfo(_Model):
    runtime: str
    runtime_version: str
    tag: str
    digest: str
    quant: str
    tokenizer_repo: str
    tokenizer_revision: str


class EvaluatorInfo(_Model):
    upstream_commit: str
    vendor_lock_sha256: Sha256


class DatasetInfo(_Model):
    revision: str
    files_sha256: dict[str, Sha256]
    """File name -> sha256."""


class EnvInfo(_Model):
    python: str
    uv_lock_sha256: Sha256
    evalenv_lock_sha256: Sha256
    git_commit: str
    git_dirty: bool
    macos: str
    chip: str
    ollama_env: dict[str, str]
    iogpu_wired_limit_mb: NonNegativeInt | None
    """``sysctl iogpu.wired_limit_mb`` (0 = macOS default); null if it could not be read."""
    gpu_recommended_max_working_set_bytes: NonNegativeInt | None
    """Metal ``recommendedMaxWorkingSetSize`` (A-005); null if it could not be read."""


class AgentInfo(_Model):
    agent_id: str
    role: str
    model_tag: str


class ErrorInfo(_Model):
    type: str
    message: str


class LlmRequest(_Model):
    endpoint: str
    num_ctx: NonNegativeInt
    num_predict: NonNegativeInt
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    repeat_penalty: float
    seed: int
    think: bool
    stop: list[str]


class TokenCounts(_Model):
    input: NonNegativeInt
    """Local tokenizer count of the rendered prompt (canonical, S4)."""
    input_reported: NonNegativeInt | None
    """The runtime's ``prompt_eval_count``; null when the runtime reported none."""
    input_cached_reported: NonNegativeInt | None
    output_visible: NonNegativeInt
    output_thinking: NonNegativeInt
    output_reported: NonNegativeInt | None
    """The runtime's ``eval_count``; null when the runtime reported none."""
    tokenizer: str
    """``<repo>@<revision>``."""


class TimingMs(_Model):
    load: NonNegativeFloat | None
    prefill: NonNegativeFloat | None
    generation: NonNegativeFloat | None
    total_reported: NonNegativeFloat | None
    wall_client: NonNegativeFloat


class QueryTotals(_Model):
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    thinking_tokens: NonNegativeInt
    llm_calls: NonNegativeInt
    wall_ms: NonNegativeFloat
    prefill_ms: NonNegativeFloat | None
    generation_ms: NonNegativeFloat | None
    load_ms: NonNegativeFloat | None
    parse_ms: NonNegativeFloat


# --- payloads: what a writer supplies, one model per D7 event type -----------------------


class RunStart(_Model):
    event_type: Literal["run_start"] = "run_start"
    kind: RunKind
    mode: str
    context_mode: str
    split: str
    query_ids: list[str]
    seeds: list[int]
    order: str
    config: dict[str, Any]
    config_hash: Sha256
    model: ModelInfo
    prompt_version: str
    prompt_sha256: Sha256
    parser_version: str
    evaluator: EvaluatorInfo
    dataset: DatasetInfo
    database_zip_sha256: Sha256
    env: EnvInfo
    agents: list[AgentInfo]
    resumed_from: RunId | None


class LlmCall(_Model):
    event_type: Literal["llm_call"] = "llm_call"
    call_id: str
    query_id: str | None
    """Null only when ``role == "warmup"``."""
    seed: int | None
    """Null only when ``role == "warmup"``."""
    agent_id: str
    role: str
    round: int | None
    parent_call_id: str | None
    attempt: NonNegativeInt
    request: LlmRequest
    prompt_sha256: Sha256
    tokens: TokenCounts
    timing_ms: TimingMs
    done_reason: str | None
    output_text: str | None
    thinking_text: str | None
    error: ErrorInfo | None

    @model_validator(mode="after")
    def _query_and_seed_unless_warmup(self) -> Self:
        if self.role != "warmup" and (self.query_id is None or self.seed is None):
            raise ValueError('query_id and seed may be null only when role == "warmup"')
        return self


class ParseResult(_Model):
    event_type: Literal["parse"] = "parse"
    query_id: str
    seed: int
    call_id: str
    parser_version: str
    ok: bool
    failure_reason: str | None
    warnings: list[str]
    n_days: NonNegativeInt
    parse_ms: NonNegativeFloat


class EvalResult(_Model):
    event_type: Literal["eval"] = "eval"
    query_id: str
    seed: int
    delivered: bool
    commonsense: dict[str, ConstraintResult] | None
    """Null when the plan was not delivered."""
    hard: dict[str, ConstraintResult] | None
    """Null when the plan was not delivered, or when D5's gating skipped the hard group."""
    commonsense_pass: bool
    hard_pass: bool
    final_pass: bool


class QueryResult(_Model):
    """Exactly one per (query, seed); the resume key."""

    event_type: Literal["query_result"] = "query_result"
    query_id: str
    seed: int
    status: Literal["delivered", "not_delivered"]
    failure_reason: str | None
    totals: QueryTotals


class Retrieval(_Model):
    """Reserved for Phase 3 (seam S1). Phase 1 never emits it."""

    event_type: Literal["retrieval"] = "retrieval"
    call_id: str
    agent_id: str
    query_id: str
    seed: int
    payload: dict[str, Any]


class RunEnd(_Model):
    """The last event of a run.

    ``counts`` MUST contain at least the keys in ``RUN_END_COUNT_KEYS``: ``queries``,
    ``seeds``, ``pairs_total``, ``pairs_done``, ``delivered``, ``llm_calls`` and ``errors``.
    A ``run_end`` without any of them fails validation; extra keys are allowed (v0.5, AQ6).
    """

    event_type: Literal["run_end"] = "run_end"
    status: Literal["succeeded", "failed", "interrupted"]
    counts: Annotated[dict[str, NonNegativeInt], AfterValidator(_all_run_end_count_keys)] = Field(
        description=(
            "Must contain at least: queries, seeds, pairs_total, pairs_done, delivered, "
            "llm_calls, errors (D7)."
        ),
        json_schema_extra={"required": list(RUN_END_COUNT_KEYS)},
    )
    metrics_path: str | None
    error: ErrorInfo | None


class HardError(_Model):
    """Any hard error that aborts a run, with its traceback."""

    event_type: Literal["error"] = "error"
    type: str
    message: str
    traceback: str


Payload = (
    RunStart | LlmCall | ParseResult | EvalResult | QueryResult | Retrieval | RunEnd | HardError
)


# --- envelope and flat wire events ---------------------------------------------------------


class Envelope(_Model):
    """The fields every line carries, whatever its event type."""

    schema_version: Literal[1]
    event_id: UUID4
    seq: NonNegativeInt
    """Per run, from 0, contiguous."""
    ts: UtcDatetime
    run_id: RunId
    event_type: str


ENVELOPE_FIELDS: Final = frozenset(Envelope.model_fields) - {"event_type"}


class RunStartEvent(RunStart, Envelope):
    """A ``run_start`` line."""


class LlmCallEvent(LlmCall, Envelope):
    """An ``llm_call`` line."""


class ParseEvent(ParseResult, Envelope):
    """A ``parse`` line."""


class EvalEvent(EvalResult, Envelope):
    """An ``eval`` line."""


class QueryResultEvent(QueryResult, Envelope):
    """A ``query_result`` line."""


class RetrievalEvent(Retrieval, Envelope):
    """A ``retrieval`` line."""


class RunEndEvent(RunEnd, Envelope):
    """A ``run_end`` line."""


class ErrorEvent(HardError, Envelope):
    """An ``error`` line."""


Event = Annotated[
    RunStartEvent
    | LlmCallEvent
    | ParseEvent
    | EvalEvent
    | QueryResultEvent
    | RetrievalEvent
    | RunEndEvent
    | ErrorEvent,
    Field(discriminator="event_type"),
]

EVENT_ADAPTER: Final[TypeAdapter[Event]] = TypeAdapter(Event)
EVENT_TYPES: Final = frozenset(
    {
        "run_start",
        "llm_call",
        "parse",
        "eval",
        "query_result",
        "retrieval",
        "run_end",
        "error",
    }
)


# --- manifest.json -------------------------------------------------------------------------


class Progress(_Model):
    done: NonNegativeInt
    total: NonNegativeInt


class RunManifest(_Model):
    """``runs/<run_id>/manifest.json`` (D7): the run_start payload plus the live status.

    The one mutable file of a run while it is in progress. Every update rewrites it
    atomically (temp file plus ``os.replace``). ``status`` and ``stage`` are exactly what
    D8's ``RunDetail`` reports.
    """

    schema_version: Literal[1]
    run_start: RunStart
    """The run_start payload without the envelope; ``event_type`` is not written."""
    status: RunStatus
    stage: RunStage | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    finished_at: UtcDatetime | None
    """Null exactly while ``status`` is queued or running (v0.5, AQ5)."""
    progress: Progress
    resumed: bool
    repaired_tail_bytes: NonNegativeInt
    metrics_path: str | None
    error: ErrorInfo | None

    @field_serializer("run_start", mode="wrap")
    def _run_start_without_envelope(
        self, value: RunStart, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(value)
        data.pop("event_type", None)
        return data

    @model_validator(mode="after")
    def _finished_at_iff_terminal(self) -> Self:
        active = self.status in ("queued", "running")
        if active and self.finished_at is not None:
            raise ValueError(f"finished_at must be null while status is {self.status!r}")
        if not active and self.finished_at is None:
            raise ValueError(f"finished_at is required once status is {self.status!r}")
        return self


# --- metrics_seed{n}.json and metrics.json -------------------------------------------------

OfficialScores = Annotated[dict[OfficialMetric, Rate], AfterValidator(_all_official_keys)]
SeedKey = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+$")]


class MetricsSeed(_Model):
    """``runs/<run_id>/metrics_seed{n}.json`` (D7)."""

    schema_version: Literal[1]
    run_id: RunId
    seed: int
    subset: bool
    n_queries: NonNegativeInt
    source: Literal["official_eval_score", "subset_aggregate"]
    scores: OfficialScores
    """The six official keys, verbatim, as rates in [0, 1]."""
    detailed: dict[str, Any]
    """``eval_score``'s second return value, or the subset equivalent."""


class MetricSummary(_Model):
    per_seed: dict[SeedKey, Rate]
    mean: Rate
    sd: NonNegativeFloat | None
    """Sample SD (ddof=1); null with fewer than two seeds."""


class Stats(_Model):
    """Over the per-(query, seed) values, warm-ups excluded. Null over an empty or all-null set."""

    mean: NonNegativeFloat | None
    median: NonNegativeFloat | None
    p95: NonNegativeFloat | None
    """Nearest rank: index ``ceil(0.95 n) - 1`` of the sorted values."""


class TokenStats(_Model):
    input: Stats
    output: Stats
    thinking: Stats


class LatencyStats(_Model):
    wall: Stats
    load: Stats
    prefill: Stats
    generation: Stats


class ParseSummary(_Model):
    attempted: NonNegativeInt
    ok: NonNegativeInt
    failure_rate: Rate | None
    """``1 - ok / attempted``; required, and null exactly when ``attempted == 0`` (v0.5, AQ7)."""

    @model_validator(mode="after")
    def _failure_rate_null_iff_nothing_attempted(self) -> Self:
        if self.attempted == 0 and self.failure_rate is not None:
            raise ValueError("failure_rate must be null when attempted == 0")
        if self.attempted > 0 and self.failure_rate is None:
            raise ValueError("failure_rate is required when attempted > 0")
        return self


class Metrics(_Model):
    """``runs/<run_id>/metrics.json`` (D7): the summary across seeds."""

    schema_version: Literal[1]
    run_id: RunId
    kind: RunKind
    config_hash: Sha256
    created_at: UtcDatetime
    finished_at: UtcDatetime
    subset: bool
    n_queries: NonNegativeInt
    seeds: list[int]
    post_check_mode: str
    metrics: Annotated[dict[OfficialMetric, MetricSummary], AfterValidator(_all_official_keys)]
    non_delivery: dict[str, NonNegativeInt]
    """Failure reason -> count."""
    parse: ParseSummary
    tokens: TokenStats
    latency_ms: LatencyStats


# --- helpers and the committed JSON Schema -------------------------------------------------

_RUN_ID_ADAPTER: Final[TypeAdapter[str]] = TypeAdapter(RunId)


def validate_run_id(run_id: str) -> str:
    """Return ``run_id`` unchanged if it has the D7 format, else raise ``ValueError``."""
    return _RUN_ID_ADAPTER.validate_python(run_id)


def new_run_id(kind: RunKind, config_hash: str, *, now: datetime | None = None) -> str:
    """Return a fresh D7 run id: ``<UTC YYYYMMDDTHHMMSSZ>-<kind>-<config_hash[:8]>-<4 hex>``."""
    if now is not None and now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return validate_run_id(
        f"{moment:%Y%m%dT%H%M%SZ}-{kind}-{config_hash[:8]}-{secrets.token_hex(2)}"
    )


def json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) committed as ``schema.json``.

    The root validates one ``events.jsonl`` line. ``$defs/RunManifest``,
    ``$defs/MetricsSeed`` and ``$defs/Metrics`` describe the other run-directory files.
    """
    schemas, definitions = TypeAdapter.json_schemas(
        [
            ("event", "validation", EVENT_ADAPTER),
            ("manifest", "validation", TypeAdapter(RunManifest)),
            ("metrics_seed", "validation", TypeAdapter(MetricsSeed)),
            ("metrics", "validation", TypeAdapter(Metrics)),
        ]
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Tripartite run-log event (ARCHITECTURE.md D7)",
        "description": (
            "The root validates one events.jsonl line. $defs/RunManifest, $defs/MetricsSeed "
            "and $defs/Metrics describe manifest.json, metrics_seed{n}.json and metrics.json."
        ),
        **schemas[("event", "validation")],
        **definitions,
    }


def render_json_schema() -> str:
    """``json_schema()`` exactly as committed in ``schema.json``."""
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    sys.stdout.write(render_json_schema())


if __name__ == "__main__":
    main()
