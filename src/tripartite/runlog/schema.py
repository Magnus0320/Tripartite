"""Run-log event schemas (ARCHITECTURE.md D7).

Every line of ``runs/<run_id>/events.jsonl`` is one event: the envelope (``schema_version``,
``event_id``, ``seq``, ``ts``, ``run_id``, ``event_type``) followed by the payload of its
event type. Readers ignore unknown event types and unknown fields, so every model here keeps
extra fields instead of rejecting them (for example the ``post_check`` field that D4 adds to
``llm_call``).

Writers build a payload model (``RunStart``, ``LlmCall``, ...) and pass it to
``RunLogWriter``, which adds the envelope. Readers get the flat ``*Event`` models, which carry
both.

The JSON Schema of the wire format is committed next to this file as ``schema.json``.
Regenerate it after any change here::

    uv run python -m tripartite.runlog.schema > src/tripartite/runlog/schema.json
"""

import json
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

SCHEMA_VERSION: Final = 1
SCHEMA_JSON_PATH: Final = Path(__file__).with_name("schema.json")

# [0-9] rather than \d: the validator's regex engine treats \d as any Unicode digit.
RUN_ID_PATTERN: Final = r"^[0-9]{8}T[0-9]{6}Z-(batch|single)-[0-9a-f]{8}-[0-9a-f]{4}$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"

RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
Sha256 = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
RunKind = Literal["batch", "single"]

ConstraintResult = tuple[bool | None, str | None]
"""One evaluator check as ``[value, message]``; a value of None means not applicable (A-014)."""


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
    """Null for a call that belongs to no query, such as the warm-up."""
    seed: int | None
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
    hard: dict[str, ConstraintResult] | None
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
    event_type: Literal["run_end"] = "run_end"
    status: Literal["succeeded", "failed", "interrupted"]
    counts: dict[str, NonNegativeInt]
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
    ts: AwareDatetime
    """RFC 3339, UTC."""
    run_id: RunId
    event_type: str

    @field_validator("ts")
    @classmethod
    def _ts_is_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("ts must be in UTC")
        return value.astimezone(UTC)


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
    """The JSON Schema (draft 2020-12) of one ``events.jsonl`` line."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Tripartite run-log event (ARCHITECTURE.md D7)",
        **EVENT_ADAPTER.json_schema(),
    }


def render_json_schema() -> str:
    """``json_schema()`` exactly as committed in ``schema.json``."""
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    sys.stdout.write(render_json_schema())


if __name__ == "__main__":
    main()
