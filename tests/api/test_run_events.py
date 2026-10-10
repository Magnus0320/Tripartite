"""``GET /api/runs/{run_id}/events``: snapshot, stage, done or error, and the ping (D8, F2)."""

import asyncio
import json
import threading
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sse_starlette import ServerSentEvent

from tests.api.helpers import (
    LEAK_FREE_ERROR,
    STAGES,
    Gate,
    GatedBridge,
    GatedClient,
    PathLeakingBridge,
    assert_no_absolute_path,
    parse_sse,
    run_batch,
    run_to_end,
    start,
    with_deps,
)
from tests.api.test_run_detail import _Broken
from tripartite.api.app import app
from tripartite.api.history import find_run_dir, load_run_detail
from tripartite.api.jobs import SSE_PING_S, ApiSettings, JobRunner
from tripartite.api.schemas import StageEvent, StreamError
from tripartite.api.sse import ping, run_events
from tripartite.pipeline.run import read_manifest


def _check_payload(name: str | None, data: Any) -> None:
    """Every ``stage`` and ``error`` payload a stream sends is its contract model (FU-34)."""
    if name == "stage":
        StageEvent.model_validate_json(data)
    elif name == "error":
        StreamError.model_validate_json(data)


def _stream(client: TestClient, run_id: str) -> Any:
    response = client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = parse_sse(response.text)
    for name, data in stream.events:
        _check_payload(name, data)
    return stream


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("stage", '{"stage": "started"}'),
        ("stage", '{"stage": "parsing", "extra": 1}'),
        ("error", '{"message": null}'),
        ("error", '{"detail": "x"}'),
    ],
)
def test_the_payload_check_refuses_what_the_contract_does_not_allow(name: str, data: str) -> None:
    with pytest.raises(ValidationError):
        _check_payload(name, data)


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


def test_the_error_event_has_no_absolute_path(
    settings: ApiSettings, synthetic_data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = PathLeakingBridge(synthetic_data, tmp_path)
    monkeypatch.setattr(app.state, "settings", with_deps(settings, bridge=bridge))
    with TestClient(app) as client:
        run_id = run_to_end(client)["run_id"]
        response = client.get(f"/api/runs/{run_id}/events")

    stream = parse_sse(response.text)
    assert [name for name, _ in stream.events] == ["snapshot", "error"]
    assert json.loads(stream.events[1][1]) == {"message": LEAK_FREE_ERROR}
    assert_no_absolute_path(response.text, tmp_path)


@pytest.mark.asyncio
async def test_an_error_message_is_cleaned_by_the_stream_itself(
    settings: ApiSettings, tmp_path: Path
) -> None:
    run_id = run_batch(settings, ["val-001"], [0])
    detail = load_run_detail(settings.runs_dir, run_id)
    leaking = detail.model_copy(
        update={"status": "failed", "error": f"OSError: cannot read {tmp_path}/x/y.txt"}
    )
    stream = run_events(
        leaking,
        read_manifest=partial(read_manifest, settings.runs_dir / run_id),
        load_detail=lambda: leaking,
        poll_s=0,
    )

    events = [event async for event in stream]

    assert events[-1].event == "error"
    assert json.loads(events[-1].data) == {"message": "OSError: cannot read y.txt"}


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
        _check_payload(event.event, event.data)
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
