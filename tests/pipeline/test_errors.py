"""What stops a run, and how (ARCHITECTURE.md D4, D5, D6, D7).

Two kinds of stop:

- **Before anything exists**: a missing, stale or fake-tokenizer calibration with the real model
  (``CalibrationMissingError``, D4; FU-25's ``run start`` part) and a held model lock. No run
  directory is created and no request is sent.
- **Hard errors during a run**: an ``error`` event with its traceback, then ``run_end`` and the
  manifest say ``failed``. The query is never silently counted as not delivered.

The real-model tests run the real code path (``TRIPARTITE_LLM`` unset) against ``FakeOllama``
behind ``httpx.MockTransport`` (``scripted_deps``).
"""

from pathlib import Path

import pytest
from filelock import FileLock

from tests.fixtures.model.fake_ollama import FakeOllama
from tests.fixtures.model.reports import (
    FAKE_REPO,
    FAKE_REVISION,
    calibration_report,
    write_calibration_report,
)
from tests.fixtures.model.run_deps import fake_deps, scripted_deps, write_config
from tripartite.config import SMOKE_CONFIG_PATH, StackConfig
from tripartite.evaluation.bridge_client import EvaluationError, FakeBridge, Plan
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord
from tripartite.llm.errors import (
    CalibrationMissingError,
    DigestMismatchError,
    ServerError,
    StackMismatchError,
    TransportError,
)
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult, LLMClient
from tripartite.pipeline.lock import ModelLockHeldError
from tripartite.pipeline.run import RunOutcome, check_server, scan_server_log, start_run
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import (
    ErrorEvent,
    LlmCallEvent,
    QueryResultEvent,
    RunEndEvent,
    RunManifest,
)

TWO_QUERIES = ["val-001", "val-002"]


@pytest.fixture
def real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIPARTITE_LLM")


def small(tmp_path: Path) -> Path:
    return write_config(tmp_path / "config.yaml", queries=TWO_QUERIES, seeds=[0])


def assert_failed(outcome: RunOutcome, error_type: str) -> list[object]:
    """The D7 shape of a hard error; returns the events."""
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert outcome.error.type == error_type, outcome.error
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    errors = [e for e in log if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].type == error_type
    assert "Traceback" in errors[0].traceback
    end = log[-1]
    assert isinstance(end, RunEndEvent)
    assert end.status == "failed"
    assert end.error is not None
    assert end.error.type == error_type
    assert end.counts["errors"] == 1
    manifest = RunManifest.model_validate_json((outcome.run_dir / "manifest.json").read_bytes())
    assert manifest.status == "failed"
    assert manifest.finished_at is not None
    assert manifest.error is not None
    assert manifest.error.type == error_type
    assert not (outcome.run_dir / "metrics.json").exists()
    return log


# --- before anything exists ------------------------------------------------------------------


@pytest.mark.usefixtures("real_mode")
@pytest.mark.parametrize(
    ("case", "match"),
    [
        ("missing", "is missing"),
        ("stale", "is stale: ollama_version"),
        ("fake_tokenizer", "is stale: written with the fake tokenizer fake-bytes@v1"),
    ],
)
def test_the_real_model_needs_a_valid_calibration_before_any_call(
    case: str, match: str, tmp_path: Path, stack: StackConfig
) -> None:
    scripted = scripted_deps(tmp_path, stack)
    path = scripted.deps.calibration_path
    if case == "missing":
        path.unlink()
    elif case == "stale":
        write_calibration_report(path, calibration_report(stack, ollama_version="0.33.1"))
    else:
        report = calibration_report(
            stack, tokenizer_repo=FAKE_REPO, tokenizer_revision=FAKE_REVISION
        )
        write_calibration_report(path, report)

    with pytest.raises(CalibrationMissingError, match=match):
        start_run(small(tmp_path), scripted.deps)
    assert scripted.server.requests == []
    assert not scripted.deps.runs_dir.exists()


def test_fake_mode_needs_no_calibration(tmp_path: Path) -> None:
    deps = fake_deps(tmp_path)
    assert not deps.calibration_path.exists()

    assert start_run(small(tmp_path), deps).status == "succeeded"


def test_a_held_model_lock_refuses_at_once(tmp_path: Path) -> None:
    client = FakeClient(FakeTokenizer())
    deps = fake_deps(tmp_path, client=client)
    deps.lock_path.parent.mkdir(parents=True)

    with FileLock(deps.lock_path, timeout=0), pytest.raises(ModelLockHeldError, match="held by"):
        start_run(small(tmp_path), deps)
    assert client.requests == []
    assert [p.name for p in deps.runs_dir.iterdir()] == [".model.lock"]


def test_the_lock_is_released_when_the_run_ends(tmp_path: Path) -> None:
    deps = fake_deps(tmp_path)
    start_run(small(tmp_path), deps)

    with FileLock(deps.lock_path, timeout=0):
        pass


# --- hard errors during a run ------------------------------------------------------------------


def test_context_overflow_aborts_the_run(tmp_path: Path) -> None:
    config = write_config(tmp_path / "c.yaml", queries=TWO_QUERIES, seeds=[0], num_predict=32000)

    log = assert_failed(start_run(config, fake_deps(tmp_path)), "ContextOverflowError")

    calls = [e for e in log if isinstance(e, LlmCallEvent)]
    assert [c.role for c in calls] == ["warmup"]  # the query itself was never sent
    assert not any(isinstance(e, QueryResultEvent) for e in log)


@pytest.mark.usefixtures("real_mode")
@pytest.mark.parametrize(
    ("offset", "error"), [(-1, "TruncationError"), (1, "TokenizerMismatchError")]
)
def test_a_failed_post_check_aborts_the_run(
    offset: int, error: str, tmp_path: Path, stack: StackConfig
) -> None:
    scripted = scripted_deps(tmp_path, stack)

    def skew_after_warm_up(stack: StackConfig, client: LLMClient) -> None:
        check_server(stack, client)
        scripted.server.token_offset = offset

    scripted.deps.server_check = skew_after_warm_up

    log = assert_failed(start_run(small(tmp_path), scripted.deps), error)

    call = [e for e in log if isinstance(e, LlmCallEvent)][-1]
    assert call.role == "planner"
    assert call.model_extra is not None
    assert call.model_extra["post_check"]["ok"] is False
    assert not any(isinstance(e, QueryResultEvent) for e in log)


@pytest.mark.usefixtures("real_mode")
def test_a_real_run_succeeds_against_the_scripted_server(
    tmp_path: Path, stack: StackConfig
) -> None:
    scripted = scripted_deps(tmp_path, stack)

    outcome = start_run(small(tmp_path), scripted.deps)

    assert outcome.status == "succeeded", outcome.error
    assert outcome.metrics is not None
    assert outcome.metrics.post_check_mode == "total"
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    calls = [e for e in log if isinstance(e, LlmCallEvent)]
    assert calls[0].tokens.tokenizer == f"{stack.tokenizer.repo}@{stack.tokenizer.revision}"
    assert all(c.model_extra and c.model_extra["post_check"]["ok"] for c in calls)
    assert outcome.metrics.metrics["Delivery Rate"].mean == 1.0


@pytest.mark.usefixtures("real_mode")
@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"version": "0.33.1"}, StackMismatchError),
        ({"pulled_digest": "f" * 64}, DigestMismatchError),
        ({"loaded_ctx": 4096}, StackMismatchError),
    ],
    ids=["version", "digest", "context_length"],
)
def test_check_server(
    change: dict[str, object], error: type[Exception], stack: StackConfig
) -> None:
    server = FakeOllama.for_stack(stack, FakeTokenizer(), loaded_ctx=32768)
    check_server(stack, server.client())  # the pinned server passes
    for key, value in change.items():
        setattr(server, key, value)

    with pytest.raises(error):
        check_server(stack, server.client())


@pytest.mark.usefixtures("real_mode")
def test_a_digest_mismatch_after_the_warm_up_aborts_the_run(
    tmp_path: Path, stack: StackConfig
) -> None:
    scripted = scripted_deps(tmp_path, stack, pulled_digest="f" * 64)

    log = assert_failed(start_run(small(tmp_path), scripted.deps), "DigestMismatchError")

    assert [e.role for e in log if isinstance(e, LlmCallEvent)] == ["warmup"]


@pytest.mark.usefixtures("real_mode")
def test_a_truncation_in_the_server_log_fails_the_run(tmp_path: Path, stack: StackConfig) -> None:
    scripted = scripted_deps(tmp_path, stack)
    line = 'level=WARN msg="truncating input prompt" limit=32768 prompt=40000\n'

    def truncate_after_warm_up(stack: StackConfig, client: LLMClient) -> None:
        check_server(stack, client)
        with scripted.log.open("a", encoding="utf-8") as f:
            f.write(line)

    scripted.deps.server_check = truncate_after_warm_up

    log = assert_failed(start_run(small(tmp_path), scripted.deps), "TruncationError")

    assert sum(isinstance(e, QueryResultEvent) for e in log) == 2  # found after the pairs


@pytest.mark.usefixtures("real_mode")
def test_a_truncation_before_the_run_started_is_not_this_runs(
    tmp_path: Path, stack: StackConfig
) -> None:
    scripted = scripted_deps(tmp_path, stack)
    with scripted.log.open("a", encoding="utf-8") as f:
        f.write('level=WARN msg="truncating input prompt" limit=4096 prompt=9000\n')

    assert start_run(small(tmp_path), scripted.deps).status == "succeeded"


def test_scan_server_log(tmp_path: Path) -> None:
    log = tmp_path / "ollama-server.log"
    log.write_text("a\ntruncating input prompt 1\n", encoding="utf-8")
    offset = log.stat().st_size
    with log.open("a", encoding="utf-8") as f:
        f.write("b\nx truncating input prompt 2\n")

    assert scan_server_log(log, offset) == ["x truncating input prompt 2"]
    assert scan_server_log(log, 10**9) == [  # the log shrank: scan all of it
        "truncating input prompt 1",
        "x truncating input prompt 2",
    ]


class FailingClient:
    """Raises ``error`` for every planner call (the warm-up passes)."""

    def __init__(self, error: Exception) -> None:
        self.inner = FakeClient(FakeTokenizer())
        self.error = error

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if "Reply with OK." in request.prompt:
            return self.inner.generate(request)
        raise self.error


def test_a_server_error_aborts_the_run(tmp_path: Path) -> None:
    client = FailingClient(ServerError("POST /api/generate: HTTP 404: model not found"))

    outcome = start_run(small(tmp_path), fake_deps(tmp_path, client=client))

    log = assert_failed(outcome, "ServerError")

    planner_calls = [e for e in log if isinstance(e, LlmCallEvent) and e.role == "planner"]
    assert len(planner_calls) == 1  # not retried
    assert planner_calls[0].error is not None
    assert planner_calls[0].error.type == "ServerError"


def test_transport_errors_after_every_retry_are_not_delivered(tmp_path: Path) -> None:
    client = FailingClient(TransportError("connection refused"))

    outcome = start_run(small(tmp_path), fake_deps(tmp_path, client=client))

    assert outcome.status == "succeeded", outcome.error  # D2: llm_error, not a hard error
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    calls = [e for e in log if isinstance(e, LlmCallEvent) and e.query_id == "val-001"]
    assert [(c.attempt, c.seed) for c in calls] == [(0, 0), (1, 0), (2, 0)]
    assert all(c.error is not None and c.error.type == "TransportError" for c in calls)
    result = next(e for e in log if isinstance(e, QueryResultEvent) and e.query_id == "val-001")
    assert (result.status, result.failure_reason, result.totals.llm_calls) == (
        "not_delivered",
        "llm_error",
        3,
    )
    assert outcome.metrics is not None
    assert outcome.metrics.non_delivery["llm_error"] == 2
    assert outcome.metrics.parse.attempted == 0
    assert outcome.metrics.parse.failure_rate is None


class CrashingBridge(FakeBridge):
    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        raise EvaluationError("KeyError", "'days'")


def test_an_evaluator_crash_aborts_the_run(tmp_path: Path) -> None:
    deps = fake_deps(tmp_path, bridge=CrashingBridge())

    log = assert_failed(start_run(small(tmp_path), deps), "EvaluationError")

    assert not any(isinstance(e, QueryResultEvent) for e in log)  # a resume re-evaluates it


def test_an_interrupted_run_is_marked_interrupted(tmp_path: Path) -> None:
    outcome = start_run(
        SMOKE_CONFIG_PATH,
        fake_deps(tmp_path, client=FailingClient(KeyboardInterrupt())),  # type: ignore[arg-type]
    )

    assert outcome.status == "interrupted"
    manifest = RunManifest.model_validate_json((outcome.run_dir / "manifest.json").read_bytes())
    assert manifest.status == "interrupted"
    assert manifest.finished_at is not None
    log = list(read_events(outcome.run_dir / "events.jsonl"))
    end = log[-1]
    assert isinstance(end, RunEndEvent)
    assert end.status == "interrupted"
    assert not any(isinstance(e, ErrorEvent) for e in log)  # not a hard error
