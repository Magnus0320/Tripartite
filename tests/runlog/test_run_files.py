"""manifest.json, metrics_seed{n}.json, metrics.json and the v0.4 event-field rules (D7)."""

import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from tests.runlog import samples
from tripartite.runlog.schema import (
    ENVELOPE_FIELDS,
    EVENT_ADAPTER,
    OFFICIAL_METRIC_KEYS,
    RUN_END_COUNT_KEYS,
    EnvInfo,
    LlmCall,
    Metrics,
    MetricsSeed,
    RunManifest,
    json_schema,
)


def test_official_metric_keys_are_eval_py_verbatim() -> None:
    assert OFFICIAL_METRIC_KEYS == (
        "Delivery Rate",
        "Commonsense Constraint Micro Pass Rate",
        "Commonsense Constraint Macro Pass Rate",
        "Hard Constraint Micro Pass Rate",
        "Hard Constraint Macro Pass Rate",
        "Final Pass Rate",
    )


# --- RunManifest -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"status": "queued", "stage": "queued", "progress": {"done": 0, "total": 6}},
        {"status": "succeeded", "stage": "done", "finished_at": samples.T0, "metrics_path": "m"},
        {"status": "failed", "stage": None, "error": {"type": "TruncationError", "message": "x"}},
        {"status": "interrupted", "created_at": None, "updated_at": None},
    ],
    ids=["running", "queued", "succeeded", "failed", "interrupted"],
)
def test_manifest_round_trip(overrides: dict[str, Any]) -> None:
    manifest = samples.manifest(**overrides)
    text = manifest.model_dump_json()

    assert RunManifest.model_validate_json(text) == manifest
    run_start = json.loads(text)["run_start"]
    assert "event_type" not in run_start
    assert not ENVELOPE_FIELDS & run_start.keys()
    assert run_start["kind"] == "batch"


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", "paused"), ("stage", "thinking"), ("repaired_tail_bytes", -1)],
)
def test_manifest_rejects_values_outside_its_sets(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        samples.manifest(**{field: value})


def test_manifest_timestamps_must_be_utc() -> None:
    with pytest.raises(ValidationError):
        RunManifest.model_validate(
            {**samples.manifest().model_dump(), "updated_at": "2026-09-23T12:00:00+05:30"}
        )


# --- MetricsSeed and Metrics -----------------------------------------------------------------


def test_metrics_seed_round_trip() -> None:
    seed = samples.metrics_seed()
    assert MetricsSeed.model_validate_json(seed.model_dump_json()) == seed
    full = samples.metrics_seed(subset=False, n_queries=180, source="official_eval_score")
    assert MetricsSeed.model_validate_json(full.model_dump_json()) == full


def test_metrics_round_trip() -> None:
    metrics = samples.metrics()
    assert Metrics.model_validate_json(metrics.model_dump_json()) == metrics
    single_seed = samples.metrics(seeds=[0])
    assert Metrics.model_validate_json(single_seed.model_dump_json()) == single_seed


@pytest.mark.parametrize(
    "scores",
    [
        {k: 0.5 for k in OFFICIAL_METRIC_KEYS if k != "Final Pass Rate"},
        dict.fromkeys(OFFICIAL_METRIC_KEYS, 0.5) | {"Final Pass Rate %": 0.5},
        dict.fromkeys(OFFICIAL_METRIC_KEYS, 50.0),
        dict.fromkeys(OFFICIAL_METRIC_KEYS, -0.1),
    ],
    ids=["missing-key", "unknown-key", "percentage", "negative"],
)
def test_metrics_seed_scores_are_exactly_the_six_rates(scores: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        samples.metrics_seed(scores=scores)


def test_metrics_needs_every_official_key_and_rates() -> None:
    full = samples.metrics().model_dump()
    missing = {
        **full,
        "metrics": {k: v for k, v in full["metrics"].items() if k != "Delivery Rate"},
    }
    with pytest.raises(ValidationError, match="missing official metric keys"):
        Metrics.model_validate(missing)
    percent = {**full, "parse": {"attempted": 27, "ok": 25, "failure_rate": 7.4}}
    with pytest.raises(ValidationError):
        Metrics.model_validate(percent)
    with pytest.raises(ValidationError):
        samples.metrics(kind="debate")


# --- llm_call: null query_id / seed only for the warm-up ------------------------------------


@pytest.mark.parametrize("field", ["query_id", "seed"])
def test_non_warmup_llm_call_with_null_query_or_seed_is_rejected(field: str) -> None:
    fields = samples.llm_call().model_dump() | {field: None}
    with pytest.raises(ValidationError, match="only when role"):
        LlmCall.model_validate(fields)
    envelope = {
        "schema_version": 1,
        "event_id": uuid.uuid4(),
        "seq": 0,
        "ts": samples.T0,
        "run_id": samples.RUN_ID,
    }
    with pytest.raises(ValidationError, match="only when role"):
        EVENT_ADAPTER.validate_python(envelope | fields)


def test_warmup_llm_call_may_have_null_or_set_query_and_seed() -> None:
    warmup = samples.warmup_call()
    assert warmup.query_id is None
    assert warmup.seed is None
    tagged = LlmCall.model_validate(warmup.model_dump() | {"query_id": "val-001", "seed": 0})
    assert tagged.query_id == "val-001"


# --- env and run_end.counts ------------------------------------------------------------------


def test_env_carries_nullable_gpu_memory_fields() -> None:
    env = samples.run_start().env.model_dump()
    nulls = env | {"iogpu_wired_limit_mb": None, "gpu_recommended_max_working_set_bytes": None}
    assert EnvInfo.model_validate(nulls).iogpu_wired_limit_mb is None
    for field in ("iogpu_wired_limit_mb", "gpu_recommended_max_working_set_bytes"):
        with pytest.raises(ValidationError):
            EnvInfo.model_validate({k: v for k, v in env.items() if k != field})


def test_run_end_count_keys_are_documented() -> None:
    assert RUN_END_COUNT_KEYS == (
        "queries",
        "seeds",
        "pairs_total",
        "pairs_done",
        "delivered",
        "llm_calls",
        "errors",
    )
    description = json_schema()["$defs"]["RunEndEvent"]["properties"]["counts"]["description"]
    assert all(key in description for key in RUN_END_COUNT_KEYS)


def test_schema_json_describes_the_run_directory_files() -> None:
    definitions = json_schema()["$defs"]
    assert {"RunManifest", "MetricsSeed", "Metrics"} <= definitions.keys()
    assert definitions["RunManifest"]["properties"]["status"]["enum"] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "interrupted",
    ]
