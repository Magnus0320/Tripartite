"""Representative payloads and run-directory files (D7), shared by the runlog tests."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tripartite.runlog.schema import (
    OFFICIAL_METRIC_KEYS,
    RUN_END_COUNT_KEYS,
    AgentInfo,
    DatasetInfo,
    EnvInfo,
    ErrorInfo,
    EvalResult,
    EvaluatorInfo,
    HardError,
    LatencyStats,
    LlmCall,
    LlmRequest,
    Metrics,
    MetricsSeed,
    MetricSummary,
    ModelInfo,
    ParseResult,
    ParseSummary,
    Payload,
    Progress,
    QueryResult,
    QueryTotals,
    Retrieval,
    RunEnd,
    RunManifest,
    RunStart,
    Stats,
    TimingMs,
    TokenCounts,
    TokenStats,
)
from tripartite.runlog.writer import RunLogWriter

SHA = "ab" * 32
RUN_ID = "20260923T120000Z-batch-abababab-1a2b"
OTHER_RUN_ID = "20260923T120001Z-single-cdcdcdcd-3c4d"
T0 = datetime(2026, 9, 23, 12, 0, 0, 123456, tzinfo=UTC)


def fixed_clock() -> datetime:
    return T0


def run_start() -> RunStart:
    return RunStart(
        kind="batch",
        mode="sole-planning",
        context_mode="full",
        split="validation",
        query_ids=["val-001", "val-002"],
        seeds=[0, 1, 2],
        order="seed-major",
        config={"run": {"name": "smoke"}, "sampling": {"temperature": 0.7}},
        config_hash=SHA,
        model=ModelInfo(
            runtime="ollama",
            runtime_version="0.0.0",
            tag="qwen3:8b-q4_K_M",
            digest="500a1f067a9f" + "0" * 52,
            quant="Q4_K_M",
            tokenizer_repo="Qwen/Qwen3-8B",
            tokenizer_revision="rev",
        ),
        prompt_version="sp-direct-v1",
        prompt_sha256=SHA,
        parser_version="rule-text/v1",
        evaluator=EvaluatorInfo(
            upstream_commit="e52c87f4ac348a3410c46dc3553c519db5ec5e23", vendor_lock_sha256=SHA
        ),
        dataset=DatasetInfo(
            revision="8736504ecfc31b7f8b7e40122873c337e83fff7c",
            files_sha256={"validation.csv": SHA, "validation_ref_info.jsonl": SHA},
        ),
        database_zip_sha256=SHA,
        env=EnvInfo(
            python="3.12.13",
            uv_lock_sha256=SHA,
            evalenv_lock_sha256=SHA,
            git_commit="0" * 40,
            git_dirty=False,
            macos="26.0",
            chip="Apple M4 Pro",
            ollama_env={"OLLAMA_NUM_PARALLEL": "1", "OLLAMA_CONTEXT_LENGTH": "32768"},
            iogpu_wired_limit_mb=0,
            gpu_recommended_max_working_set_bytes=17_179_869_184,
        ),
        agents=[AgentInfo(agent_id="planner", role="planner", model_tag="qwen3:8b-q4_K_M")],
        resumed_from=None,
    )


def _request(num_predict: int = 4096) -> LlmRequest:
    return LlmRequest(
        endpoint="/api/generate",
        num_ctx=32768,
        num_predict=num_predict,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        repeat_penalty=1.0,
        seed=0,
        think=False,
        stop=["<|im_end|>", "<|endoftext|>"],
    )


def llm_call(**extra: Any) -> LlmCall:
    return LlmCall(
        call_id="call-1",
        query_id="val-001",
        seed=0,
        agent_id="planner",
        role="planner",
        round=None,
        parent_call_id=None,
        attempt=0,
        request=_request(),
        prompt_sha256=SHA,
        tokens=TokenCounts(
            input=12000,
            input_reported=11500,
            input_cached_reported=None,
            output_visible=900,
            output_thinking=0,
            output_reported=901,
            tokenizer="Qwen/Qwen3-8B@rev",
        ),
        timing_ms=TimingMs(
            load=0.0,
            prefill=8000.5,
            generation=30000.25,
            total_reported=38001.0,
            wall_client=38100.0,
        ),
        done_reason="stop",
        output_text="Day 1:\nCurrent City: from Ithaca to Charlotte\nBreakfast: Café → Charlotte\n",
        thinking_text=None,
        error=None,
        **extra,
    )


def warmup_call() -> LlmCall:
    return LlmCall(
        call_id="warmup-1",
        query_id=None,
        seed=None,
        agent_id="planner",
        role="warmup",
        round=None,
        parent_call_id=None,
        attempt=0,
        request=_request(num_predict=1),
        prompt_sha256=SHA,
        tokens=TokenCounts(
            input=20,
            input_reported=20,
            input_cached_reported=None,
            output_visible=1,
            output_thinking=0,
            output_reported=1,
            tokenizer="Qwen/Qwen3-8B@rev",
        ),
        timing_ms=TimingMs(
            load=1500.0, prefill=10.0, generation=1.0, total_reported=1511.0, wall_client=1520.0
        ),
        done_reason="length",
        output_text="OK",
        thinking_text=None,
        error=None,
    )


def failed_call() -> LlmCall:
    return LlmCall(
        call_id="call-2",
        query_id="val-002",
        seed=0,
        agent_id="planner",
        role="planner",
        round=None,
        parent_call_id=None,
        attempt=2,
        request=_request(),
        prompt_sha256=SHA,
        tokens=TokenCounts(
            input=13000,
            input_reported=None,
            input_cached_reported=None,
            output_visible=0,
            output_thinking=0,
            output_reported=None,
            tokenizer="Qwen/Qwen3-8B@rev",
        ),
        timing_ms=TimingMs(
            load=None, prefill=None, generation=None, total_reported=None, wall_client=600000.0
        ),
        done_reason=None,
        output_text=None,
        thinking_text=None,
        error=ErrorInfo(type="ReadTimeout", message="timed out after 600 s"),
    )


def parse_ok() -> ParseResult:
    return ParseResult(
        query_id="val-001",
        seed=0,
        call_id="call-1",
        parser_version="rule-text/v1",
        ok=True,
        failure_reason=None,
        warnings=["missing_field:dinner"],
        n_days=3,
        parse_ms=1.5,
    )


def parse_failed() -> ParseResult:
    return ParseResult(
        query_id="val-002",
        seed=0,
        call_id="call-2",
        parser_version="rule-text/v1",
        ok=False,
        failure_reason="no_day_blocks",
        warnings=[],
        n_days=0,
        parse_ms=0.2,
    )


def eval_delivered() -> EvalResult:
    return EvalResult(
        query_id="val-001",
        seed=0,
        delivered=True,
        commonsense={"is_valid_restaurants": (True, None), "is_not_absent": (False, "No plan")},
        hard={"valid_cost": (None, None), "valid_room_type": (True, None)},
        commonsense_pass=False,
        hard_pass=True,
        final_pass=False,
    )


def eval_not_delivered() -> EvalResult:
    return EvalResult(
        query_id="val-002",
        seed=0,
        delivered=False,
        commonsense=None,
        hard=None,
        commonsense_pass=False,
        hard_pass=False,
        final_pass=False,
    )


def query_result() -> QueryResult:
    return QueryResult(
        query_id="val-001",
        seed=0,
        status="delivered",
        failure_reason=None,
        totals=QueryTotals(
            input_tokens=12000,
            output_tokens=900,
            thinking_tokens=0,
            llm_calls=1,
            wall_ms=38200.0,
            prefill_ms=8000.5,
            generation_ms=30000.25,
            load_ms=0.0,
            parse_ms=1.5,
        ),
    )


def retrieval() -> Retrieval:
    return Retrieval(call_id="call-1", agent_id="planner", query_id="val-001", seed=0, payload={})


def run_end() -> RunEnd:
    return RunEnd(
        status="failed",
        counts=dict.fromkeys(RUN_END_COUNT_KEYS, 1) | {"llm_calls": 3},
        metrics_path=None,
        error=ErrorInfo(type="TruncationError", message="prompt_eval_count below bound"),
    )


def hard_error() -> HardError:
    return HardError(
        type="TruncationError",
        message="prompt_eval_count below bound",
        traceback='Traceback (most recent call last):\n  File "run.py", line 1\n',
    )


def all_payloads() -> list[Payload]:
    """At least one payload of every event type, in a plausible run order."""
    return [
        run_start(),
        warmup_call(),
        llm_call(),
        parse_ok(),
        eval_delivered(),
        query_result(),
        failed_call(),
        parse_failed(),
        eval_not_delivered(),
        retrieval(),
        hard_error(),
        run_end(),
    ]


def manifest(**overrides: Any) -> RunManifest:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "run_start": run_start(),
        "status": "running",
        "stage": "generating",
        "created_at": T0,
        "updated_at": T0,
        "finished_at": None,
        "progress": Progress(done=1, total=6),
        "resumed": True,
        "repaired_tail_bytes": 37,
        "metrics_path": None,
        "error": None,
    }
    return RunManifest(**(fields | overrides))


def _scores(value: float) -> dict[str, float]:
    return dict.fromkeys(OFFICIAL_METRIC_KEYS, value)


def metrics_seed(**overrides: Any) -> MetricsSeed:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "seed": 0,
        "subset": True,
        "n_queries": 9,
        "source": "subset_aggregate",
        "scores": _scores(0.5) | {"Final Pass Rate": 0.0},
        "detailed": {"Commonsense Constraint": {"easy": {"3": {}}}, "Hard Constraint": {}},
    }
    return MetricsSeed(**(fields | overrides))


def metrics(**overrides: Any) -> Metrics:
    stats = Stats(mean=1200.5, median=1100.0, p95=2000.0)
    empty = Stats(mean=None, median=None, p95=None)
    fields: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "kind": "batch",
        "config_hash": SHA,
        "created_at": T0,
        "finished_at": T0,
        "subset": True,
        "n_queries": 9,
        "seeds": [0, 1, 2],
        "post_check_mode": "total",
        "metrics": {
            key: MetricSummary(per_seed={"0": 0.5, "1": 0.25, "2": 0.75}, mean=0.5, sd=0.25)
            for key in OFFICIAL_METRIC_KEYS
        },
        "non_delivery": {"no_day_blocks": 2, "llm_error": 1},
        "parse": ParseSummary(attempted=27, ok=25, failure_rate=1 - 25 / 27),
        "tokens": TokenStats(input=stats, output=stats, thinking=empty),
        "latency_ms": LatencyStats(wall=stats, load=empty, prefill=stats, generation=stats),
    }
    return Metrics(**(fields | overrides))


# --- a whole run directory, and the git history its commit lives in (M6) ----------------------

GENERATION = {"num_predict": 4096, "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0}
ARCHITECTURE_LINE = "ARCHITECTURE.md · v0.12 · 2026-10-07"
NEVER_SYNCED = ("events.jsonl", "plans_seed0.jsonl", "per_plan_eval_seed0.jsonl", "blobs")
"""Run-directory entries that MLflow must never receive (D7 §MLflow)."""


def git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]
    done = subprocess.run(
        ["git", *identity, *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def write_git_repo(repo: Path, first_line: str | None = ARCHITECTURE_LINE) -> str:
    """A throwaway repository with one commit; return its id.

    The commit holds ``ARCHITECTURE.md`` starting with ``first_line``, or no such file for None.
    """
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "--quiet")
    name = "ARCHITECTURE.md" if first_line is not None else "README.md"
    (repo / name).write_text(f"{first_line}\n\n# Changelog\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "--quiet", "--no-gpg-sign", "-m", "architecture")
    return git(repo, "rev-parse", "HEAD")


def write_run_dir(
    runs_dir: Path,
    *,
    run_id: str = RUN_ID,
    git_commit: str = "0" * 40,
    num_ctxs: tuple[int, ...] = (32768,),
    **metrics_overrides: Any,
) -> Path:
    """Write a succeeded run as D7 lays it out, with files that are never synced, and return it."""
    run_dir = runs_dir / run_id
    (run_dir / "blobs").mkdir(parents=True)
    start = run_start()
    start = start.model_copy(
        update={
            "kind": "single" if "-single-" in run_id else "batch",
            "config": {**start.config, "generation": GENERATION},
            "env": start.env.model_copy(update={"git_commit": git_commit}),
        }
    )
    summary = metrics(run_id=run_id, kind=start.kind, **metrics_overrides)
    files = {
        "manifest.json": manifest(
            run_start=start,
            status="succeeded",
            stage="done",
            finished_at=T0,
            metrics_path="metrics.json",
        ),
        "metrics.json": summary,
        **{
            f"metrics_seed{seed}.json": metrics_seed(run_id=run_id, seed=seed)
            for seed in summary.seeds
        },
    }
    for name, model in files.items():
        (run_dir / name).write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    with RunLogWriter(run_dir / "events.jsonl", run_id, clock=fixed_clock) as writer:
        writer.write(start)
        for num_ctx in num_ctxs:
            call = llm_call()
            request = call.request.model_copy(update={"num_ctx": num_ctx})
            writer.write(call.model_copy(update={"request": request}))
        writer.write(run_end())
    (run_dir / "plans_seed0.jsonl").write_text('{"idx": 1, "query": "q", "plan": []}\n')
    (run_dir / "per_plan_eval_seed0.jsonl").write_text('{"idx": 1}\n')
    (run_dir / "blobs" / f"{SHA}.txt").write_text("a rendered prompt\n")
    return run_dir
