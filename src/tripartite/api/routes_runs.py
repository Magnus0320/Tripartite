"""``/api/runs`` (ARCHITECTURE.md D8, F2): start a single run, read it, and follow it.

``POST /api/runs`` starts one run of one query and one seed through the job runner
(``jobs.py``). It answers 202 once the run exists on disk as ``queued``; 404 for an unknown
query_id; 409 when this server is already running a job (``active_run_id`` names it) or another
process holds ``runs/.model.lock`` (``active_run_id`` is null); and 503 when the data is missing
or the run cannot start, for example without a valid token calibration (D4). A run that cannot
start leaves nothing on disk.

``GET /api/runs/{run_id}`` and its ``/events`` stream read the run directory (``history.py``,
``sse.py``). Both answer 404 for an id that is malformed or has no ``manifest.json``, 503 when
the run's query text cannot be read from the data, and 500 with the reader's message when the
run log is corrupt (D7: the API never repairs one).
"""

import asyncio
from functools import partial
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sse_starlette import EventSourceResponse

from tripartite.api import routes_queries
from tripartite.api.history import (
    QueryUnavailableError,
    RunNotFoundError,
    find_run_dir,
    load_run_detail,
)
from tripartite.api.jobs import ApiSettings, JobActiveError, JobRunner
from tripartite.api.schemas import ErrorDetail, RunAccepted, RunConflict, RunDetail, RunRequest
from tripartite.api.sse import event_stream, run_events
from tripartite.config import ConfigError
from tripartite.data.planner_inputs import get_planner_input
from tripartite.llm.errors import LLMError
from tripartite.pipeline.lock import ModelLockHeldError
from tripartite.pipeline.run import read_manifest
from tripartite.planner.prompt import PromptError
from tripartite.runlog.reader import RunLogError

router = APIRouter()

CANNOT_START: Final = (
    ConfigError,
    LLMError,
    PromptError,
    RunLogError,
    ValidationError,
    *routes_queries.DATA_ERRORS,
)
"""What ``open_run`` raises before a run exists, other than a held model lock."""
Responses = dict[int | str, dict[str, Any]]
UNKNOWN_RUN: Final[Responses] = {404: {"model": ErrorDetail, "description": "Unknown run_id"}}
QUERY_UNAVAILABLE: Final[Responses] = {
    500: {"model": ErrorDetail, "description": "The run log is corrupt"},
    503: {"model": ErrorDetail, "description": "The data is missing or invalid"},
}


def _settings(request: Request) -> ApiSettings:
    settings: ApiSettings = request.app.state.settings
    return settings


def _query_exists(query_id: str) -> None:
    try:
        get_planner_input(query_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    except routes_queries.DATA_ERRORS as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _conflict(detail: str, active_run_id: str | None) -> JSONResponse:
    body = RunConflict(detail=detail, active_run_id=active_run_id)
    return JSONResponse(status_code=409, content=body.model_dump())


@router.post(
    "/api/runs",
    status_code=202,
    response_model=RunAccepted,
    responses={
        404: {"model": ErrorDetail, "description": "Unknown query_id"},
        409: {
            "model": RunConflict,
            "description": "A job is running, or runs/.model.lock is held",
        },
        503: {
            "model": ErrorDetail,
            "description": "The data is missing or invalid, or the run cannot start",
        },
    },
)
async def start_run(body: RunRequest, request: Request) -> RunAccepted | JSONResponse:
    """Start a single run of one validation query with one seed. One job runs at a time."""
    jobs: JobRunner = request.app.state.jobs
    await asyncio.to_thread(_query_exists, body.query_id)
    try:
        run_id = await jobs.submit(body.query_id, body.seed)
    except JobActiveError as exc:
        return _conflict(str(exc), exc.run_id)
    except ModelLockHeldError as exc:
        return _conflict(str(exc), None)
    except CANNOT_START as exc:
        detail = f"the run cannot start: {type(exc).__name__}: {exc}"
        raise HTTPException(status_code=503, detail=detail) from None
    return RunAccepted(run_id=run_id, status="queued")


def _detail(settings: ApiSettings, run_id: str) -> RunDetail:
    try:
        return load_run_detail(settings.runs_dir, run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except QueryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except RunLogError as exc:
        raise HTTPException(status_code=500, detail=f"the run log is corrupt: {exc}") from None


@router.get("/api/runs/{run_id}", responses={**UNKNOWN_RUN, **QUERY_UNAVAILABLE})
def get_run(run_id: str, request: Request) -> RunDetail:
    """One run: its status and stage, and a single run's plan, constraints and usage."""
    return _detail(_settings(request), run_id)


@router.get(
    "/api/runs/{run_id}/events",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": (
                "Server-sent events: `snapshot` (RunDetail), `stage` ({stage}) on each change, "
                "then `done` (RunDetail) or `error` ({message}), and the stream closes. "
                "A `: ping` comment is sent every 15 s."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **UNKNOWN_RUN,
        **QUERY_UNAVAILABLE,
    },
)
async def get_run_events(run_id: str, request: Request) -> EventSourceResponse:
    """Follow one run until it is finished; a finished run sends its two events and closes."""
    settings = _settings(request)
    first = await asyncio.to_thread(_detail, settings, run_id)
    run_dir = find_run_dir(settings.runs_dir, run_id)
    events = run_events(
        first,
        read_manifest=partial(read_manifest, run_dir),
        load_detail=partial(load_run_detail, settings.runs_dir, run_id),
        poll_s=settings.sse_poll_s,
    )
    return event_stream(events, ping_s=settings.sse_ping_s)
