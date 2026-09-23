"""Readers ignore unknown event types and unknown fields (ARCHITECTURE.md D7)."""

import json
import uuid
from pathlib import Path

import pytest

from tests.runlog import samples
from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.schema import LlmCallEvent, RunStartEvent
from tripartite.runlog.writer import RunLogWriter


def _append(path: Path, obj: dict[str, object]) -> None:
    with path.open("a") as file:
        file.write(json.dumps(obj) + "\n")


def _future_event(seq: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "seq": seq,
        "ts": "2026-09-23T12:00:01Z",
        "run_id": samples.RUN_ID,
        "event_type": "debate_turn",
        "agent_id": "critic",
        "payload": {"text": "a later phase's event"},
    }


def test_unknown_event_types_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())
    _append(path, _future_event(seq=1))
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.llm_call())

    events = list(read_events(path))
    assert [type(e) for e in events] == [RunStartEvent, LlmCallEvent]
    assert [e.seq for e in events] == [0, 2]


def test_unknown_fields_are_accepted_and_kept(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    post_check = {
        "mode": "total",
        "lcp": 512,
        "expected_min": 12000,
        "expected_max": 12000,
        "observed": 12000,
        "ok": True,
    }
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.llm_call(post_check=post_check))
    line = json.loads(path.read_text())
    line["tokens"]["future_counter"] = 3
    line["from_a_newer_writer"] = "ignored"
    path.write_text(json.dumps(line) + "\n")

    (event,) = read_events(path)
    assert isinstance(event, LlmCallEvent)
    assert event.model_extra == {"post_check": post_check, "from_a_newer_writer": "ignored"}
    assert event.tokens.model_extra == {"future_counter": 3}
    assert event.tokens.input == 12000


def test_an_unknown_event_type_still_needs_a_valid_envelope(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    future = _future_event(seq=0)
    del future["seq"]
    _append(path, future)

    with pytest.raises(RunLogError, match=r":1: invalid envelope"):
        list(read_events(path))
