"""``tripartite run start --resume`` (ARCHITECTURE.md D7 §Resume, Q10; A-023)."""

import json
from pathlib import Path

import pytest
from filelock import FileLock

from tests.fixtures.model.run_deps import fake_deps, scripted_deps
from tripartite.config import SMOKE_CONFIG_PATH, StackConfig
from tripartite.evaluation.bridge_client import EvaluationError, FakeBridge, Plan
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult, LLMClient
from tripartite.pipeline.lock import ModelLockHeldError
from tripartite.pipeline.resume import ResumeError, resume_run
from tripartite.pipeline.run import RunOutcome, start_run
from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.schema import (
    LlmCallEvent,
    MetricsSeed,
    QueryResultEvent,
    RunEndEvent,
    RunManifest,
    RunStartEvent,
)


class InterruptingClient:
    """A fake client that is interrupted (Ctrl-C) on its ``stop_at``-th planner call."""

    def __init__(self, stop_at: int, inner: LLMClient | None = None) -> None:
        self.inner = inner or FakeClient(FakeTokenizer())
        self.stop_at = stop_at
        self.planner_calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if "Reply with OK." not in request.prompt:
            self.planner_calls += 1
            if self.planner_calls == self.stop_at:
                raise KeyboardInterrupt
        return self.inner.generate(request)


def manifest(outcome: RunOutcome) -> RunManifest:
    return RunManifest.model_validate_json((outcome.run_dir / "manifest.json").read_bytes())


def interrupted(tmp_path: Path, stop_at: int = 4) -> RunOutcome:
    outcome = start_run(
        SMOKE_CONFIG_PATH, fake_deps(tmp_path / "a", client=InterruptingClient(stop_at))
    )
    assert outcome.status == "interrupted"
    return outcome


def resume_deps(tmp_path: Path, outcome: RunOutcome, **changes: object) -> object:
    return fake_deps(tmp_path / "b", runs_dir=outcome.run_dir.parent, **changes)


def test_a_resume_runs_only_the_missing_pairs(tmp_path: Path) -> None:
    first = interrupted(tmp_path)
    client = FakeClient(FakeTokenizer())

    outcome = resume_run(first.run_id, resume_deps(tmp_path, first, client=client))

    assert outcome.status == "succeeded", outcome.error
    assert outcome.run_id == first.run_id
    prompts = [json.loads(body)["prompt"] for body in client.requests]
    assert len(prompts) == 1 + 27 - 3  # a fresh warm-up, then the 24 pairs not done
    assert "Reply with OK." in prompts[0]
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    lines = (outcome.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["seq"] for line in lines] == list(range(len(lines)))
    starts = [e for e in log if isinstance(e, RunStartEvent)]
    assert [s.resumed_from for s in starts] == [None, first.run_id]
    assert starts[0].config_hash == starts[1].config_hash
    ends = [e for e in log if isinstance(e, RunEndEvent)]
    assert [e.status for e in ends] == ["interrupted", "succeeded"]
    results = [(e.query_id, e.seed) for e in log if isinstance(e, QueryResultEvent)]
    assert len(results) == len(set(results)) == 27
    final = manifest(outcome)
    assert (final.status, final.resumed, final.repaired_tail_bytes) == ("succeeded", True, 0)
    assert final.created_at == manifest(first).created_at
    assert final.run_start.resumed_from == first.run_id


def test_a_resumed_run_scores_like_an_uninterrupted_one(tmp_path: Path) -> None:
    first = interrupted(tmp_path, stop_at=13)
    resumed = resume_run(first.run_id, resume_deps(tmp_path, first))
    whole = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path / "c"))

    for seed in (0, 1, 2):
        for name in (f"plans_seed{seed}.jsonl", f"per_plan_eval_seed{seed}.jsonl"):
            assert (resumed.run_dir / name).read_bytes() == (whole.run_dir / name).read_bytes()
        a, b = (
            MetricsSeed.model_validate_json((run.run_dir / f"metrics_seed{seed}.json").read_bytes())
            for run in (resumed, whole)
        )
        assert (a.scores, a.detailed) == (b.scores, b.detailed)


def test_a_partial_last_line_is_repaired(tmp_path: Path) -> None:
    first = interrupted(tmp_path)
    events = first.run_dir / "events.jsonl"
    partial = b'{"schema_version": 1, "event_id": "half-writ'
    with events.open("ab") as f:
        f.write(partial)

    outcome = resume_run(first.run_id, resume_deps(tmp_path, first))

    assert outcome.status == "succeeded", outcome.error
    assert manifest(outcome).repaired_tail_bytes == len(partial)
    [corrupt] = outcome.run_dir.glob("events.corrupt-*.txt")
    assert corrupt.read_bytes() == partial
    list(read_events(events))  # the strict reader accepts the repaired log


def test_a_corrupt_line_before_the_end_is_a_hard_error(tmp_path: Path) -> None:
    first = interrupted(tmp_path)
    events = first.run_dir / "events.jsonl"
    lines = events.read_bytes().splitlines(keepends=True)
    events.write_bytes(b"".join([lines[0], b"not json\n", *lines[1:]]))

    with pytest.raises(RunLogError, match="invalid JSON"):
        resume_run(first.run_id, resume_deps(tmp_path, first))
    assert manifest(first).status == "interrupted"


def test_a_failed_run_resumes_after_the_cause_is_fixed(tmp_path: Path) -> None:
    class CrashOnce(FakeBridge):
        def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
            if record.query_id == "val-041":
                raise EvaluationError("KeyError", "'days'")
            return super().per_plan(record, plan)

    first = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path / "a", bridge=CrashOnce()))
    assert first.status == "failed"

    outcome = resume_run(first.run_id, resume_deps(tmp_path, first))

    assert outcome.status == "succeeded", outcome.error
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    calls = [e for e in log if isinstance(e, LlmCallEvent) and e.query_id == "val-041"]
    assert [c.seed for c in calls] == [0, 0, 1, 2]  # the crashed pair is generated again


def test_a_succeeded_run_is_final(tmp_path: Path) -> None:
    done = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path / "a"))

    with pytest.raises(ResumeError, match="is succeeded"):
        resume_run(done.run_id, resume_deps(tmp_path, done))


def test_a_tampered_config_is_refused(tmp_path: Path) -> None:
    first = interrupted(tmp_path)
    path = first.run_dir / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["run_start"]["config"]["generation"]["temperature"] = 0.0
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ResumeError, match="hashes to"):
        resume_run(first.run_id, resume_deps(tmp_path, first))


def test_a_different_stack_is_refused(
    tmp_path: Path, stack: StackConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run started against the (scripted) real model cannot be finished in fake mode."""
    monkeypatch.delenv("TRIPARTITE_LLM")
    scripted = scripted_deps(tmp_path / "a", stack)
    scripted.deps.client = InterruptingClient(2, scripted.server.client())
    scripted.deps.server_check = lambda _stack, _client: None
    first = start_run(SMOKE_CONFIG_PATH, scripted.deps)
    assert first.status == "interrupted", first.error
    monkeypatch.setenv("TRIPARTITE_LLM", "fake")

    with pytest.raises(ResumeError, match="the stack differs"):
        resume_run(first.run_id, resume_deps(tmp_path, first))


def test_a_run_in_progress_is_not_touched(tmp_path: Path) -> None:
    first = interrupted(tmp_path)
    deps = resume_deps(tmp_path, first)
    events = first.run_dir / "events.jsonl"
    with events.open("ab") as f:
        f.write(b'{"partial')
    before = events.read_bytes()

    with FileLock(deps.lock_path, timeout=0), pytest.raises(ModelLockHeldError):  # type: ignore[attr-defined]
        resume_run(first.run_id, deps)  # type: ignore[arg-type]
    assert events.read_bytes() == before  # no repair without the lock


@pytest.mark.parametrize("run_id", ["nope", "20260928T120000Z-batch-00000000-0000"])
def test_an_unknown_run_is_refused(run_id: str, tmp_path: Path) -> None:
    with pytest.raises(ResumeError):
        resume_run(run_id, fake_deps(tmp_path))
