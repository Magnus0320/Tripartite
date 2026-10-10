"""Schema round trip and the committed JSON Schema (ARCHITECTURE.md D7)."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from tests.runlog import samples
from tripartite.runlog.schema import (
    ENVELOPE_FIELDS,
    EVENT_ADAPTER,
    EVENT_TYPES,
    RUN_ID_PATTERN,
    SCHEMA_JSON_PATH,
    Payload,
    RetrievalEvent,
    RunManifest,
    RunStart,
    RunStartEvent,
    new_run_id,
    render_json_schema,
    validate_run_id,
)

ENVELOPE_ORDER = ["schema_version", "event_id", "seq", "ts", "run_id", "event_type"]


def _envelope(seq: int = 0, **overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": uuid.uuid4(),
        "seq": seq,
        "ts": samples.T0,
        "run_id": samples.RUN_ID,
        **overrides,
    }


def test_samples_cover_every_event_type() -> None:
    assert {p.event_type for p in samples.all_payloads()} == EVENT_TYPES


@pytest.mark.parametrize("payload", samples.all_payloads(), ids=lambda p: p.event_type)
def test_round_trip(payload: Payload) -> None:
    event = EVENT_ADAPTER.validate_python({**_envelope(), **payload.model_dump()})
    line = event.model_dump_json()

    assert EVENT_ADAPTER.validate_json(line) == event
    decoded = json.loads(line)
    assert list(decoded)[: len(ENVELOPE_ORDER)] == ENVELOPE_ORDER
    assert decoded["ts"] == "2026-09-23T12:00:00.123456Z"
    assert type(payload).model_validate(event.model_dump(exclude=set(ENVELOPE_FIELDS))) == payload


def test_committed_json_schema_is_current() -> None:
    assert SCHEMA_JSON_PATH.read_text(encoding="utf-8") == render_json_schema(), (
        "schema.json is stale; regenerate it with: "
        "uv run python -m tripartite.runlog.schema > src/tripartite/runlog/schema.json"
    )


def test_retrieval_validates_an_empty_payload() -> None:
    event = EVENT_ADAPTER.validate_python({**_envelope(), **samples.retrieval().model_dump()})
    assert isinstance(event, RetrievalEvent)
    assert event.payload == {}


def test_new_run_id_has_the_d7_format() -> None:
    now = datetime(2026, 9, 23, 7, 5, 9, tzinfo=UTC)
    run_id = new_run_id("single", "0123456789abcdef" * 4, now=now)
    assert re.fullmatch(RUN_ID_PATTERN, run_id)
    assert run_id.startswith("20260923T070509Z-single-01234567-")


def test_new_run_id_converts_to_utc_and_refuses_naive_times() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert new_run_id(
        "batch", samples.SHA, now=datetime(2026, 9, 23, 12, 0, tzinfo=ist)
    ).startswith("20260923T063000Z-batch-")
    with pytest.raises(ValueError, match="timezone-aware"):
        new_run_id("batch", samples.SHA, now=datetime(2026, 9, 23, 12, 0))


@pytest.mark.parametrize(
    "run_id",
    [
        "20260923T120000Z-batch-abababab",
        "20260923T120000-batch-abababab-1a2b",
        "20260923T120000Z-debate-abababab-1a2b",
        "20260923T120000Z-batch-ABABABAB-1a2b",
        "2026092\N{FULLWIDTH DIGIT THREE}T120000Z-batch-abababab-1a2b",
    ],
)
def test_malformed_run_ids_are_rejected(run_id: str) -> None:
    with pytest.raises(ValidationError):
        validate_run_id(run_id)


@pytest.mark.parametrize(
    "ts",
    ["2026-09-23T12:00:00+01:00", "2026-09-23T12:00:00"],
    ids=["non-utc", "naive"],
)
def test_ts_must_be_utc(ts: str) -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**_envelope(ts=ts), **samples.run_end().model_dump()})


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python(
            {**_envelope(schema_version=2), **samples.run_end().model_dump()}
        )


def test_sha256_fields_are_checked() -> None:
    fields = samples.run_start().model_dump()
    fields["config_hash"] = "not-a-sha"
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python({**_envelope(), **fields})


# --- FU-30: run_start.allow_dirty -------------------------------------------------------------


def _run_start_line(**extra: Any) -> str:
    """A ``run_start`` line as the pipeline wrote it before the field was declared."""
    event = EVENT_ADAPTER.validate_python({**_envelope(), **samples.run_start().model_dump()})
    fields = json.loads(event.model_dump_json())
    assert "allow_dirty" not in fields
    return json.dumps(fields | extra)


def test_a_run_start_without_allow_dirty_still_validates_and_reads_false() -> None:
    event = EVENT_ADAPTER.validate_json(_run_start_line())

    assert isinstance(event, RunStartEvent)
    assert event.allow_dirty is False


def test_a_manifest_without_allow_dirty_still_validates_and_reads_false() -> None:
    text = samples.manifest().model_dump_json()
    assert "allow_dirty" not in text

    assert RunManifest.model_validate_json(text).run_start.allow_dirty is False


def test_allow_dirty_true_round_trips_in_events_and_manifests() -> None:
    event = EVENT_ADAPTER.validate_json(_run_start_line(allow_dirty=True))
    assert isinstance(event, RunStartEvent)
    assert event.allow_dirty is True
    assert json.loads(event.model_dump_json())["allow_dirty"] is True

    start = samples.run_start().model_copy(update={"allow_dirty": True})
    manifest = samples.manifest(run_start=start)
    stored = json.loads(manifest.model_dump_json())
    assert stored["run_start"]["allow_dirty"] is True
    assert RunManifest.model_validate(stored) == manifest


@pytest.mark.parametrize("mode", ["python", "json"])
def test_allow_dirty_false_is_never_written(mode: str) -> None:
    """Files keep their bytes: the key appears only when the flag was used (D7 §Resume)."""
    start = RunStart(**(samples.run_start().model_dump() | {"allow_dirty": False}))

    assert start.allow_dirty is False
    assert "allow_dirty" not in start.model_dump(mode=mode)
    assert "allow_dirty" not in samples.manifest(run_start=start).model_dump(mode=mode)["run_start"]


def test_allow_dirty_must_be_a_boolean() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_json(_run_start_line(allow_dirty="sometimes"))


def test_the_json_schema_declares_allow_dirty_as_optional() -> None:
    schema = json.loads(render_json_schema())
    for name in ("RunStart", "RunStartEvent"):
        definition = schema["$defs"][name]
        assert definition["properties"]["allow_dirty"]["type"] == "boolean"
        assert definition["properties"]["allow_dirty"]["default"] is False
        assert "allow_dirty" not in definition["required"]
