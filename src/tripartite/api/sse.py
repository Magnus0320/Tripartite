"""``GET /api/runs/{run_id}/events`` as server-sent events (ARCHITECTURE.md D8).

A stream sends ``snapshot`` (the ``RunDetail``) at once, ``stage`` (``{"stage": …}``) on each
change, and finally ``done`` (the ``RunDetail``) for a succeeded run or ``error``
(``{"message": …}``) for a failed or interrupted one, then closes. A run that is already
finished gets ``snapshot`` and then ``done`` or ``error``. The ``stage`` and ``error`` data are
the ``StageEvent`` and ``StreamError`` models of the contract (FU-34).

The pipeline reports a stage only by rewriting ``manifest.json``, so a stream reads the manifest
every ``poll_s`` seconds and sends the stages it sees. A stage shorter than that, such as
``parsing``, may never be sent; the order of those that are is always D8's. Polling
``GET /api/runs/{run_id}`` is the supported fallback, and it reads the same file.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

from sse_starlette import EventSourceResponse, ServerSentEvent

from tripartite.api.history import ACTIVE
from tripartite.api.messages import public_message
from tripartite.api.schemas import RunDetail, RunStage, StageEvent, StreamError
from tripartite.runlog.schema import RunManifest


def _detail_event(name: str, detail: RunDetail) -> ServerSentEvent:
    return ServerSentEvent(event=name, data=detail.model_dump_json())


def _stage_event(stage: RunStage) -> ServerSentEvent:
    return ServerSentEvent(event="stage", data=StageEvent(stage=stage).model_dump_json())


def _error_event(message: str) -> ServerSentEvent:
    # The text is the run's error, which manifest.json keeps in full, so it is not logged again.
    error = StreamError(message=public_message(message, log=False))
    return ServerSentEvent(event="error", data=error.model_dump_json())


async def run_events(
    first: RunDetail,
    *,
    read_manifest: Callable[[], RunManifest],
    load_detail: Callable[[], RunDetail],
    poll_s: float,
) -> AsyncIterator[ServerSentEvent]:
    """The events of one stream. ``first`` is the snapshot; ``read_manifest`` and ``load_detail``
    read the run again."""
    yield _detail_event("snapshot", first)
    status, stage, final = first.status, first.stage, first
    while status in ACTIVE:
        await asyncio.sleep(poll_s)
        manifest = read_manifest()
        status = manifest.status
        if status in ACTIVE and manifest.stage is not None and manifest.stage != stage:
            stage = manifest.stage
            yield _stage_event(stage)
    if final.status in ACTIVE:
        final = await asyncio.to_thread(load_detail)
        if final.stage is not None and final.stage != stage:
            yield _stage_event(final.stage)
    if final.status == "succeeded":
        yield _detail_event("done", final)
    else:
        yield _error_event(final.error or f"the run was {final.status}")


def ping() -> ServerSentEvent:
    """The keep-alive comment, ``: ping``."""
    return ServerSentEvent(comment="ping")


def event_stream(events: AsyncIterator[ServerSentEvent], *, ping_s: float) -> EventSourceResponse:
    return EventSourceResponse(events, ping=ping_s, ping_message_factory=ping)
