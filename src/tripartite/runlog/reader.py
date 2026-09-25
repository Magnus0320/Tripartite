"""Streaming reader for ``runs/<run_id>/events.jsonl`` (ARCHITECTURE.md D7).

Every line must be one complete JSON object with a valid envelope. Lines whose
``event_type`` this version does not know are skipped, and unknown fields are kept on the
returned models (``model_extra``) rather than rejected.

The reader is strict by default: a corrupt log is normally a bug. Only the final line can be
partial after a crash, because the writer appends whole lines and fsyncs each one (A-023).
``repair_tail`` removes such a line before a resume appends to the log, and
``read_events(..., tolerate_partial_tail=True)`` skips it without touching the file. A bad
line anywhere else is always a ``RunLogError``.
"""

import io
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tripartite.runlog.schema import EVENT_ADAPTER, EVENT_TYPES, Envelope, Event

_CHUNK = 64 * 1024


class RunLogError(Exception):
    """A run log cannot be read or appended to."""


def iter_lines(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(line number, decoded object)`` for every line, numbered from 1."""
    for lineno, raw, _ in _numbered_lines(path):
        yield lineno, _decode(path, lineno, raw)


def read_envelopes(path: Path) -> Iterator[tuple[int, Envelope]]:
    """Yield ``(line number, envelope)`` for every line, including unknown event types."""
    for lineno, obj in iter_lines(path):
        yield lineno, _envelope(path, lineno, obj)


def read_events(path: Path, tolerate_partial_tail: bool = False) -> Iterator[Event]:
    """Yield every event of a known type, in file order.

    With ``tolerate_partial_tail``, a final line that is incomplete (no trailing newline) or
    is not a JSON object with a valid envelope is skipped instead of raising. The file is
    never modified. Any other bad line still raises ``RunLogError``.
    """
    for lineno, raw, is_last in _numbered_lines(path):
        try:
            obj = _decode(path, lineno, raw)
            envelope = _envelope(path, lineno, obj)
        except RunLogError:
            if tolerate_partial_tail and is_last:
                return
            raise
        if envelope.event_type not in EVENT_TYPES:
            continue
        try:
            yield EVENT_ADAPTER.validate_python(obj)
        except ValidationError as exc:
            raise RunLogError(
                f"{path}:{lineno}: invalid {envelope.event_type} event: {exc}"
            ) from exc


def repair_tail(path: Path) -> int:
    """Cut a partial final line off the log, for resume (D7). Return the bytes discarded.

    Only the final line is inspected. If the file does not end with a newline, or its last
    line is not a JSON object with a valid envelope, the file is truncated just after the
    newline that precedes that line. The discarded bytes are first saved to
    ``events.corrupt-<UTC YYYYMMDDTHHMMSSZ>.txt`` next to the log. Returns 0, and changes
    nothing, when the final line is whole.
    """
    with path.open("r+b") as file:
        size = file.seek(0, os.SEEK_END)
        if size == 0:
            return 0
        start = _start_of_last_line(file, size)
        file.seek(start)
        tail = file.read()
        if _is_whole_line(path, tail):
            return 0
        corrupt = path.parent / f"events.corrupt-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.txt"
        with corrupt.open("xb") as saved:
            saved.write(tail)
            saved.flush()
            os.fsync(saved.fileno())
        file.truncate(start)
        file.flush()
        os.fsync(file.fileno())
    return len(tail)


def _numbered_lines(path: Path) -> Iterator[tuple[int, bytes, bool]]:
    """Yield ``(line number, raw bytes, is the last line)``."""
    with path.open("rb") as file:
        previous: tuple[int, bytes] | None = None
        for lineno, raw in enumerate(file, start=1):
            if previous is not None:
                yield previous[0], previous[1], False
            previous = (lineno, raw)
        if previous is not None:
            yield previous[0], previous[1], True


def _decode(path: Path, lineno: int, raw: bytes) -> dict[str, Any]:
    if not raw.endswith(b"\n"):
        raise RunLogError(f"{path}:{lineno}: truncated line (no trailing newline)")
    try:
        obj = json.loads(raw)
    except ValueError as exc:  # JSONDecodeError, or UnicodeDecodeError for invalid UTF-8
        raise RunLogError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise RunLogError(f"{path}:{lineno}: not a JSON object")
    return obj


def _envelope(path: Path, lineno: int, obj: dict[str, Any]) -> Envelope:
    try:
        return Envelope.model_validate(obj)
    except ValidationError as exc:
        raise RunLogError(f"{path}:{lineno}: invalid envelope: {exc}") from exc


def _is_whole_line(path: Path, raw: bytes) -> bool:
    try:
        _envelope(path, 0, _decode(path, 0, raw))
    except RunLogError:
        return False
    return True


def _start_of_last_line(file: io.BufferedRandom, size: int) -> int:
    """Offset just after the newline that precedes the final line (0 if there is none)."""
    file.seek(size - 1)
    end = size - 1 if file.read(1) == b"\n" else size
    while end > 0:
        begin = max(0, end - _CHUNK)
        file.seek(begin)
        found = file.read(end - begin).rfind(b"\n")
        if found != -1:
            return begin + found + 1
        end = begin
    return 0
