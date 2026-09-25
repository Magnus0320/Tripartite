"""repair_tail and read_events(tolerate_partial_tail=...) (D7 §half-written last line, A-023)."""

import json
import random
import re
from pathlib import Path

import pytest

from tests.runlog import samples
from tripartite.runlog.reader import RunLogError, read_events, repair_tail
from tripartite.runlog.writer import RunLogWriter

CORRUPT_NAME = re.compile(r"^events\.corrupt-[0-9]{8}T[0-9]{6}Z\.txt$")


@pytest.fixture
def full_log(tmp_path: Path) -> bytes:
    """A complete log with one event of every type, including multi-byte UTF-8 text."""
    path = tmp_path / "source" / "events.jsonl"
    path.parent.mkdir()
    with RunLogWriter(path, samples.RUN_ID) as log:
        for payload in samples.all_payloads():
            log.write(payload)
    return path.read_bytes()


def _log(tmp_path: Path, name: str, content: bytes) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    path = directory / "events.jsonl"
    path.write_bytes(content)
    return path


def _corrupt_files(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if p.name != "events.jsonl")


def test_repair_after_a_cut_at_any_offset_leaves_the_complete_lines(
    tmp_path: Path, full_log: bytes
) -> None:
    rng = random.Random(20260923)
    boundaries = [i + 1 for i, byte in enumerate(full_log) if byte == ord("\n")]
    offsets = sorted(
        {0, 1, len(full_log) - 1, len(full_log)}
        | {b - 1 for b in boundaries}
        | {b + 1 for b in boundaries[:-1]}
        | {rng.randrange(len(full_log) + 1) for _ in range(200)}
    )

    for offset in offsets:
        cut = full_log[:offset]
        path = _log(tmp_path, f"cut-{offset}", cut)
        complete = cut.count(b"\n")
        kept = cut[: cut.rfind(b"\n") + 1]

        discarded = repair_tail(path)

        assert discarded == len(cut) - len(kept), offset
        assert path.read_bytes() == kept, offset
        assert len(list(read_events(path))) == complete, offset
        corrupt = _corrupt_files(path)
        if discarded:
            assert len(corrupt) == 1, offset
            assert CORRUPT_NAME.match(corrupt[0].name), corrupt[0].name
            assert corrupt[0].read_bytes() == cut[len(kept) :], offset
        else:
            assert corrupt == [], offset
        with RunLogWriter(path, samples.RUN_ID) as log:
            assert log.next_seq == complete, offset


def test_an_intact_or_empty_log_is_left_alone(tmp_path: Path, full_log: bytes) -> None:
    intact = _log(tmp_path, "intact", full_log)
    assert repair_tail(intact) == 0
    assert intact.read_bytes() == full_log
    assert _corrupt_files(intact) == []

    empty = _log(tmp_path, "empty", b"")
    assert repair_tail(empty) == 0
    assert empty.read_bytes() == b""


@pytest.mark.parametrize(
    "last_line",
    [
        b"{not json\n",
        b'{"a": "\xff"}\n',
        b'["a list, not an object"]\n',
        b'{"schema_version": 1, "event_type": "run_end"}\n',
        b"\n",
    ],
    ids=["invalid-json", "invalid-utf8", "not-an-object", "no-envelope", "empty-line"],
)
def test_a_whole_but_invalid_final_line_is_discarded(
    tmp_path: Path, full_log: bytes, last_line: bytes
) -> None:
    path = _log(tmp_path, "bad-tail", full_log + last_line)

    assert repair_tail(path) == len(last_line)
    assert path.read_bytes() == full_log
    assert len(list(read_events(path))) == full_log.count(b"\n")


def test_a_bad_line_before_the_last_still_raises(tmp_path: Path, full_log: bytes) -> None:
    lines = full_log.splitlines(keepends=True)
    damaged = b"".join([*lines[:2], b"{not json\n", *lines[2:]])
    path = _log(tmp_path, "bad-middle", damaged)

    assert repair_tail(path) == 0
    assert path.read_bytes() == damaged
    with pytest.raises(RunLogError, match=r":3: invalid JSON"):
        list(read_events(path))
    with pytest.raises(RunLogError, match=r":3: invalid JSON"):
        list(read_events(path, tolerate_partial_tail=True))
    with pytest.raises(RunLogError, match=r":3: invalid JSON"):
        RunLogWriter(path, samples.RUN_ID)


def test_repair_only_touches_the_tail_when_an_earlier_line_is_bad(
    tmp_path: Path, full_log: bytes
) -> None:
    lines = full_log.splitlines(keepends=True)
    damaged = b"".join([lines[0], b"{not json\n", *lines[1:]])
    path = _log(tmp_path, "bad-middle-and-tail", damaged + lines[1][:20])

    assert repair_tail(path) == 20
    assert path.read_bytes() == damaged
    with pytest.raises(RunLogError, match=r":2: invalid JSON"):
        list(read_events(path))


def test_read_events_is_strict_by_default(tmp_path: Path, full_log: bytes) -> None:
    cut = full_log[: len(full_log) - 10]
    path = _log(tmp_path, "cut", cut)

    with pytest.raises(RunLogError, match="truncated line"):
        list(read_events(path))

    events = list(read_events(path, tolerate_partial_tail=True))
    assert len(events) == cut.count(b"\n")
    assert path.read_bytes() == cut
    assert _corrupt_files(path) == []


def test_tolerance_does_not_cover_a_whole_line_with_an_invalid_payload(
    tmp_path: Path, full_log: bytes
) -> None:
    last = json.loads(full_log.splitlines()[-1])
    del last["status"]
    last["seq"] += 1
    path = _log(tmp_path, "bad-payload", full_log + json.dumps(last).encode() + b"\n")

    assert repair_tail(path) == 0
    with pytest.raises(RunLogError, match="invalid run_end event"):
        list(read_events(path, tolerate_partial_tail=True))
