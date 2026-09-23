"""Append-only writer for ``runs/<run_id>/events.jsonl`` (ARCHITECTURE.md D7).

Each event is one compact JSON line. The line is flushed and fsynced before ``write``
returns, so a crash never loses an event that was reported as written.
"""

import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from tripartite.runlog.reader import RunLogError, read_envelopes
from tripartite.runlog.schema import (
    ENVELOPE_FIELDS,
    EVENT_ADAPTER,
    SCHEMA_VERSION,
    Event,
    Payload,
    validate_run_id,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunLogWriter:
    """Writes the events of one run.

    Opening a log that already exists (resume, D7) continues its ``seq``. The existing lines
    must belong to the same run and be numbered 0, 1, 2, ... without gaps.
    """

    def __init__(self, path: Path, run_id: str, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = path
        self.run_id = validate_run_id(run_id)
        self._clock = clock
        self._next_seq = 0
        if path.exists():
            for lineno, envelope in read_envelopes(path):
                if envelope.run_id != self.run_id:
                    raise RunLogError(
                        f"{path}:{lineno}: line belongs to run {envelope.run_id}, not {run_id}"
                    )
                if envelope.seq != self._next_seq:
                    raise RunLogError(
                        f"{path}:{lineno}: seq {envelope.seq}, expected {self._next_seq}"
                    )
                self._next_seq += 1
        self._file = path.open("ab")

    @property
    def next_seq(self) -> int:
        return self._next_seq

    def write(self, payload: Payload) -> Event:
        """Add the envelope to ``payload``, append it as one line, and return the event."""
        if self._file.closed:
            raise RunLogError(f"{self.path}: writer is closed")
        fields = payload.model_dump()
        if clash := ENVELOPE_FIELDS & fields.keys():
            raise RunLogError(f"payload must not set envelope fields: {sorted(clash)}")
        event = EVENT_ADAPTER.validate_python(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": uuid.uuid4(),
                "seq": self._next_seq,
                "ts": self._clock(),
                "run_id": self.run_id,
                **fields,
            }
        )
        self._file.write(event.model_dump_json().encode() + b"\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._next_seq += 1
        return event

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
