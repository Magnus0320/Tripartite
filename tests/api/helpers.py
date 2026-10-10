"""Helpers for the run tests (api): gates around the fake client and bridge, run factories and
an SSE parser. Everything runs in fake mode on the synthetic data, in a temporary ``runs/``."""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tripartite.api.jobs import ApiSettings, single_config
from tripartite.config import REPO_ROOT, SINGLE_CONFIG_PATH, RunConfig, load_run_config
from tripartite.evaluation.aggregate import OfficialScores
from tripartite.evaluation.bridge_client import (
    EvaluationError,
    EvaluatorBridge,
    FakeBridge,
    Plan,
)
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult, LLMClient
from tripartite.pipeline.run import RunDeps, RunSession, close_run, execute, open_run

WAIT_S = 10.0
TERMINAL = ("succeeded", "failed", "interrupted")
STAGES = ["queued", "generating", "parsing", "evaluating", "done"]
"""D8's stage order."""
RICH_PLAN = (
    "Day 1:\n"
    "Current City: from Aville to Synthville\n"
    "Transportation: Flight Number: F0000001, from Aville to Synthville\n"
    "Breakfast: -\n"
    "Attraction: Synth Museum, Synthville; Synth Park, Synthville;\n"
    "Lunch: Cafe One, Synthville\n"
    "Dinner: Diner Two, Synthville\n"
    "Accommodation: Cozy Room, Synthville\n"
    "Day 2:\n"
    "Current City: Synthville\n"
    "Transportation: -\n"
    "Breakfast: Cafe One, Synthville\n"
    "Attraction: -\n"
    "Lunch: -\n"
    "Dinner: -\n"
    "Accommodation: -"
)
"""A hand-written two-day plan in the official format (not model output)."""


@dataclass
class Gate:
    """Blocks a call until the test opens it; ``entered`` says the call has arrived."""

    entered: threading.Event = field(default_factory=threading.Event)
    opened: threading.Event = field(default_factory=threading.Event)

    def pass_through(self) -> None:
        self.entered.set()
        assert self.opened.wait(WAIT_S), "the gate was never opened"

    def open(self) -> None:
        self.opened.set()

    def wait_entered(self) -> None:
        assert self.entered.wait(WAIT_S), "the gated call never happened"


class GatedClient:
    """The fake client, with every planner call (not the warm-up) held at ``gate``."""

    def __init__(self, gate: Gate, inner: LLMClient | None = None) -> None:
        self.gate = gate
        self._inner = inner or FakeClient(FakeTokenizer())

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if request.options.num_predict > 1:
            self.gate.pass_through()
        return self._inner.generate(request)


class GatedBridge:
    """The fake bridge, with ``per_plan`` held at ``gate``."""

    def __init__(self, gate: Gate, inner: EvaluatorBridge | None = None) -> None:
        self.gate = gate
        self._inner = inner or FakeBridge()

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        self.gate.pass_through()
        return self._inner.per_plan(record, plan)

    def aggregate(
        self, plans_path: Path, records_path: Path, set_type: str = "validation"
    ) -> OfficialScores:
        return self._inner.aggregate(plans_path, records_path, set_type)

    def close(self) -> None:
        self._inner.close()


NO_VALIDATION_CSV = "[Errno 2] No such file or directory: 'raw/validation.csv'"
"""What the loader says about an empty data root, as a response body gives it (FU-35)."""


def assert_no_absolute_path(body: str, tmp_path: Path) -> None:
    """FU-35: a response body names neither the temporary data root and ``runs/`` nor the
    repository by an absolute path."""
    for root in (tmp_path, tmp_path.resolve(), REPO_ROOT):
        assert str(root) not in body, body


class PathLeakingBridge(FakeBridge):
    """A bridge whose ``per_plan`` fails with absolute paths in its message: one under the data
    root, one under the repository and one elsewhere under ``tmp_path``."""

    def __init__(self, data_root: Path, tmp_path: Path) -> None:
        super().__init__()
        self.message = (
            f"[Errno 2] No such file or directory: '{tmp_path / 'db files' / 'flights.csv'}'; "
            f"read {data_root / 'raw' / 'validation.csv'} "
            f"from {REPO_ROOT / 'vendor' / 'travelplanner' / 'eval.py'}"
        )

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        raise EvaluationError("FileNotFoundError", self.message)


LEAK_FREE_ERROR = (
    "EvaluationError: FileNotFoundError: [Errno 2] No such file or directory: 'flights.csv'; "
    "read raw/validation.csv from vendor/travelplanner/eval.py"
)
"""``RunDetail.error`` of a run that failed in ``PathLeakingBridge``."""


def deps_for(settings: ApiSettings, **changes: Any) -> RunDeps:
    """``RunDeps`` on the settings' ``runs/``, with no pause between transport retries."""
    return RunDeps(
        runs_dir=settings.runs_dir,
        lock_path=settings.lock_path,
        sleep=lambda _s: None,
        **changes,
    )


def with_deps(settings: ApiSettings, **changes: Any) -> ApiSettings:
    """``settings`` whose jobs get ``changes`` (a client, a bridge, a calibration path…)."""
    return ApiSettings(
        runs_dir=settings.runs_dir,
        make_deps=lambda: deps_for(settings, **changes),
        sse_ping_s=settings.sse_ping_s,
        sse_poll_s=settings.sse_poll_s,
    )


def responding(text: str) -> FakeClient:
    """A fake client whose every reply is ``text``."""
    return FakeClient(FakeTokenizer(), respond=lambda _request: text)


def open_stale_run(settings: ApiSettings, *, queued: bool = False) -> str:
    """A single run that a dead server left behind: opened, never executed, lock released."""
    session: RunSession = open_run(
        single_config(SINGLE_CONFIG_PATH, "val-001", 0), deps_for(settings)
    )
    if queued:
        session.update(status="queued", stage="queued")
    close_run(session)
    return session.run_id


def batch_config(queries: list[str], seeds: list[int]) -> RunConfig:
    data = load_run_config(SINGLE_CONFIG_PATH).model_dump(mode="json")
    return RunConfig.model_validate({**data, "kind": "batch", "queries": queries, "seeds": seeds})


def run_batch(settings: ApiSettings, queries: list[str], seeds: list[int]) -> str:
    """A finished batch run, made by the pipeline as ``tripartite run start`` makes one."""
    outcome = execute(open_run(batch_config(queries, seeds), deps_for(settings)))
    assert outcome.status == "succeeded", outcome.error
    return outcome.run_id


def start(client: TestClient, query_id: str = "val-001", **body: Any) -> str:
    response = client.post("/api/runs", json={"query_id": query_id, **body})
    assert response.status_code == 202, response.text
    run_id: str = response.json()["run_id"]
    return run_id


def wait_finished(client: TestClient, run_id: str) -> dict[str, Any]:
    """Poll ``GET /api/runs/{run_id}`` until the run is finished and the runner is free."""
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        detail: dict[str, Any] = response.json()
        jobs = client.app.state.jobs  # type: ignore[attr-defined]
        if detail["status"] in TERMINAL and jobs.active_run_id is None:
            return detail
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish within {WAIT_S} s")


def run_to_end(client: TestClient, query_id: str = "val-001", **body: Any) -> dict[str, Any]:
    return wait_finished(client, start(client, query_id, **body))


@dataclass(frozen=True)
class Sse:
    events: list[tuple[str, str]]
    """(event, data) in order."""
    comments: list[str]


def parse_sse(body: str) -> Sse:
    events, comments = [], []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith(":"):
                comments.append(line[1:].strip())
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        if name is not None:
            events.append((name, "\n".join(data)))
    return Sse(events, comments)
