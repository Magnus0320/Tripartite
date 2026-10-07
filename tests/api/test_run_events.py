"""``GET /api/runs/{run_id}/events``: snapshot, stage, done or error, and the ping (D8, F2)."""

import asyncio
import json
import threading
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sse_starlette import ServerSentEvent

from tests.api.helpers import (
    STAGES,
    Gate,
    GatedBridge,
    GatedClient,
    parse_sse,
    run_to_end,
    start,
    with_deps,
)
from tests.api.test_run_detail import _Broken
from tripartite.api.app import app
from tripartite.api.history import find_run_dir, load_run_detail
from tripartite.api.jobs import SSE_PING_S, ApiSettings, JobRunner
from tripartite.api.sse import ping, run_events
from tripartite.pipeline.run import read_manifest


def _stream(client: TestClient, run_id: str) -> Any:
    response = client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def _in_d8_order(stages: list[str]) -> bool:
    positions = [STAGES.index(stage) for stage in stages]
    return positions == sorted(set(positions))


def test_a_finished_run_sends_snapshot_then_done_and_closes(client: TestClient) -> None:
    detail = run_to_end(client)

    stream = _stream(client, detail["run_id"])

    assert [name for name, _ in stream.events] == ["snapshot", "done"]
    assert json.loads(stream.events[0][1]) == detail
    assert json.loads(stream.events[1][1]) == detail


def test_a_finished_failed_run_sends_snapshot_then_error(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state, "settings", with_deps(settings, bridge=_Broken()))
    with TestClient(app) as client:
        detail = run_to_end(client)

        stream = _stream(client, detail["run_id"])

    assert [name for name, _ in stream.events] == ["snapshot", "error"]
    assert json.loads(stream.events[0][1])["status"] == "failed"
    assert json.loads(stream.events[1][1]) == {"message": detail["error"]}


def test_following_a_run_from_its_start_ends_with_done(client: TestClient) -> None:
    run_id = start(client, "val-003")

    stream = _stream(client, run_id)  # returns when the stream closes

    names = [name for name, _ in stream.events]
    assert names[0] == "snapshot"
    assert names[-1] == "done"
    assert set(names[1:-1]) <= {"stage"}
    assert _in_d8_order(
        [json.loads(data)["stage"] for name, data in stream.events if name == "stage"]
    )
    final = json.loads(stream.events[-1][1])
    assert final["status"] == "succeeded"
    assert final["item"]["query_id"] == "val-003"
    assert final == client.get(f"/api/runs/{run_id}").json()


async def _follow(settings: ApiSettings, run_id: str, seen: list[ServerSentEvent]) -> None:
    run_dir = find_run_dir(settings.runs_dir, run_id)
    events = run_events(
        load_run_detail(settings.runs_dir, run_id),
        read_manifest=partial(read_manifest, run_dir),
        load_detail=partial(load_run_detail, settings.runs_dir, run_id),
        poll_s=0.002,
    )
    async for event in events:
        seen.append(event)


async def _until(condition: Any) -> None:
    async with asyncio.timeout(10):
        while not condition():
            await asyncio.sleep(0.002)


def _stages(seen: list[ServerSentEvent]) -> list[str]:
    return [json.loads(e.data)["stage"] for e in seen if e.event == "stage"]


@pytest.mark.asyncio
async def test_a_live_run_sends_each_stage_it_passes_through(settings: ApiSettings) -> None:
    generating, evaluating = Gate(), Gate()
    gated = with_deps(settings, client=GatedClient(generating), bridge=GatedBridge(evaluating))
    runner = JobRunner(gated)
    run_id = await runner.submit("val-001", 0)
    await asyncio.to_thread(generating.wait_entered)

    seen: list[ServerSentEvent] = []
    follower = asyncio.create_task(_follow(settings, run_id, seen))
    await _until(lambda: len(seen) == 1)
    snapshot = json.loads(seen[0].data)
    assert seen[0].event == "snapshot"
    assert (snapshot["status"], snapshot["stage"], snapshot["item"]) == (
        "running",
        "generating",
        None,
    )

    await asyncio.sleep(0.02)
    assert len(seen) == 1  # nothing changes while the model is generating

    generating.open()
    await _until(lambda: "evaluating" in _stages(seen))
    assert seen[-1].event == "stage"  # still running: the evaluator has not answered

    evaluating.open()
    await asyncio.wait_for(follower, 10)

    stages = _stages(seen)
    assert _in_d8_order(stages)
    assert stages[-2:] == ["evaluating", "done"]
    assert [e.event for e in seen] == ["snapshot", *["stage"] * len(stages), "done"]
    final = json.loads(seen[-1].data)
    assert (final["status"], final["stage"]) == ("succeeded", "done")
    assert final["item"]["delivered"] is True
    await _until(lambda: runner.active_run_id is None)


@pytest.mark.asyncio
async def test_a_live_run_that_fails_ends_with_error(settings: ApiSettings) -> None:
    generating = Gate()
    gated = with_deps(settings, client=GatedClient(generating), bridge=_Broken())
    runner = JobRunner(gated)
    run_id = await runner.submit("val-001", 0)
    await asyncio.to_thread(generating.wait_entered)

    seen: list[ServerSentEvent] = []
    follower = asyncio.create_task(_follow(settings, run_id, seen))
    await _until(lambda: len(seen) == 1)
    generating.open()
    await asyncio.wait_for(follower, 10)

    assert seen[0].event == "snapshot"
    assert seen[-1].event == "error"
    assert "done" not in [e.event for e in seen]
    message = json.loads(seen[-1].data)
    assert set(message) == {"message"}
    assert message["message"].startswith("EvaluationError: ")
    await _until(lambda: runner.active_run_id is None)


def test_a_ping_comment_is_sent_while_a_run_is_followed(
    settings: ApiSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = Gate()
    slow = with_deps(settings, client=GatedClient(gate))
    fast_ping = ApiSettings(
        runs_dir=slow.runs_dir, make_deps=slow.make_deps, sse_ping_s=0.02, sse_poll_s=0.005
    )
    monkeypatch.setattr(app.state, "settings", fast_ping)
    with TestClient(app) as client:
        run_id = start(client)
        gate.wait_entered()
        timer = threading.Timer(0.3, gate.open)
        timer.start()

        response = client.get(f"/api/runs/{run_id}/events")
        timer.join()

    assert ": ping\r\n" in response.text
    stream = parse_sse(response.text)
    assert stream.comments.count("ping") >= 2
    assert set(stream.comments) == {"ping"}
    assert [name for name, _ in stream.events][-1] == "done"


def test_the_ping_is_every_15_s_and_is_the_bare_comment() -> None:
    assert ApiSettings().sse_ping_s == SSE_PING_S == 15.0
    assert ping().encode() == b": ping\r\n\r\n"
