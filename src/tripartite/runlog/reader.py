"""Streaming reader for ``runs/<run_id>/events.jsonl`` (ARCHITECTURE.md D7).

Every line must be one complete JSON object with a valid envelope. Lines whose
``event_type`` this version does not know are skipped, and unknown fields are kept on the
returned models (``model_extra``) rather than rejected.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tripartite.runlog.schema import EVENT_ADAPTER, EVENT_TYPES, Envelope, Event


class RunLogError(Exception):
    """A run log cannot be read or appended to."""


def iter_lines(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(line number, decoded object)`` for every line, numbered from 1."""
    with path.open("rb") as file:
        for lineno, raw in enumerate(file, start=1):
            if not raw.endswith(b"\n"):
                raise RunLogError(f"{path}:{lineno}: truncated line (no trailing newline)")
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RunLogError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise RunLogError(f"{path}:{lineno}: not a JSON object")
            yield lineno, obj


def read_envelopes(path: Path) -> Iterator[tuple[int, Envelope]]:
    """Yield ``(line number, envelope)`` for every line, including unknown event types."""
    for lineno, obj in iter_lines(path):
        yield lineno, _envelope(path, lineno, obj)


def read_events(path: Path) -> Iterator[Event]:
    """Yield every event of a known type, in file order."""
    for lineno, obj in iter_lines(path):
        envelope = _envelope(path, lineno, obj)
        if envelope.event_type not in EVENT_TYPES:
            continue
        try:
            yield EVENT_ADAPTER.validate_python(obj)
        except ValidationError as exc:
            raise RunLogError(
                f"{path}:{lineno}: invalid {envelope.event_type} event: {exc}"
            ) from exc


def _envelope(path: Path, lineno: int, obj: dict[str, Any]) -> Envelope:
    try:
        return Envelope.model_validate(obj)
    except ValidationError as exc:
        raise RunLogError(f"{path}:{lineno}: invalid envelope: {exc}") from exc
