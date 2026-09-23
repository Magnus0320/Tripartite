"""RunLogWriter and read_events (ARCHITECTURE.md D7)."""

import json
import uuid
from pathlib import Path

import pytest

from tests.runlog import samples
from tripartite.runlog import writer as writer_module
from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.writer import RunLogWriter


def _write_all(path: Path) -> list[object]:
    with RunLogWriter(path, samples.RUN_ID, clock=samples.fixed_clock) as log:
        return [log.write(p) for p in samples.all_payloads()]


def test_writer_adds_the_envelope_and_the_reader_returns_the_same_events(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    written = _write_all(path)

    assert list(read_events(path)) == written
    lines = path.read_bytes().split(b"\n")
    assert lines[-1] == b""
    assert len(lines) - 1 == len(written)
    envelopes = [json.loads(line) for line in lines[:-1]]
    assert [e["seq"] for e in envelopes] == list(range(len(written)))
    assert {e["run_id"] for e in envelopes} == {samples.RUN_ID}
    assert {e["schema_version"] for e in envelopes} == {1}
    assert all(e["ts"] == "2026-09-23T12:00:00.123456Z" for e in envelopes)
    event_ids = [uuid.UUID(e["event_id"]) for e in envelopes]
    assert len(set(event_ids)) == len(event_ids)
    assert {i.version for i in event_ids} == {4}


def test_every_line_is_flushed_and_fsynced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "events.jsonl"
    synced: list[int] = []
    monkeypatch.setattr(writer_module.os, "fsync", lambda fd: synced.append(fd))

    with RunLogWriter(path, samples.RUN_ID) as log:
        for n, payload in enumerate(samples.all_payloads()[:3], start=1):
            log.write(payload)
            assert len(synced) == n
            assert path.read_bytes().count(b"\n") == n


def test_reopening_continues_the_sequence(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())
        log.write(samples.llm_call())
    with RunLogWriter(path, samples.RUN_ID) as log:
        assert log.next_seq == 2
        log.write(samples.run_end())

    assert [e.seq for e in read_events(path)] == [0, 1, 2]


def test_reopening_refuses_another_runs_log(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())

    with pytest.raises(RunLogError, match="belongs to run"):
        RunLogWriter(path, samples.OTHER_RUN_ID)


def test_reopening_refuses_a_gap_in_seq(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())
    line = json.loads(path.read_text())
    line["seq"] = 5
    with path.open("a") as file:
        file.write(json.dumps(line) + "\n")

    with pytest.raises(RunLogError, match="seq 5, expected 1"):
        RunLogWriter(path, samples.RUN_ID)


def test_writer_refuses_a_malformed_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pattern"):
        RunLogWriter(tmp_path / "events.jsonl", "run-1")


def test_payload_cannot_override_the_envelope(tmp_path: Path) -> None:
    with (
        RunLogWriter(tmp_path / "events.jsonl", samples.RUN_ID) as log,
        pytest.raises(RunLogError, match="envelope fields"),
    ):
        log.write(samples.llm_call(seq=7))


def test_writer_refuses_to_write_after_close(tmp_path: Path) -> None:
    log = RunLogWriter(tmp_path / "events.jsonl", samples.RUN_ID)
    log.close()
    with pytest.raises(RunLogError, match="closed"):
        log.write(samples.run_start())


def test_reader_reports_the_line_number_of_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())
    with path.open("a") as file:
        file.write("{not json\n")

    with pytest.raises(RunLogError, match=r"events\.jsonl:2: invalid JSON"):
        list(read_events(path))


def test_reader_rejects_a_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_start())
    with path.open("a") as file:
        file.write('{"schema_version": 1')

    with pytest.raises(RunLogError, match=r":2: truncated line"):
        list(read_events(path))


def test_reader_rejects_a_known_event_with_a_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with RunLogWriter(path, samples.RUN_ID) as log:
        log.write(samples.run_end())
    line = json.loads(path.read_text())
    del line["status"]
    path.write_text(json.dumps(line) + "\n")

    with pytest.raises(RunLogError, match=r":1: invalid run_end event"):
        list(read_events(path))
