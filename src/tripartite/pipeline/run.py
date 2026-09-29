"""A run of the sole planner, from its config to its scores (ARCHITECTURE.md D1, D4, D5, D7).

``tripartite run start --config <path>`` calls ``open_run`` then ``execute``:

1. **Before anything is created or called.** With the real model, the token calibration must be
   valid (``CalibrationMissingError`` otherwise, D4 §Before calibration has run); fake mode needs
   none and checks in mode ``total``. The prompt file must match its recorded sha256 (D6), and
   ``runs/.model.lock`` is taken without waiting (D4 §Concurrency).
2. **The run directory** ``runs/<run_id>/`` (D7): ``manifest.json`` (status ``running``),
   ``events.jsonl`` with its ``run_start``, and ``blobs/``.
3. **The warm-up** (D4): one ``num_predict: 1`` call, logged as ``role: "warmup"``. With the real
   model, the loaded model is then checked against ``configs/stack.yaml`` (``/api/version``, and
   ``/api/ps`` for the digest and ``context_length``): a mismatch is a hard error.
4. **The pairs**, seed-major in query_id order (D4). ``run_one`` passes only the ``PlannerInput``
   to the planner (D3), logs one ``llm_call`` per attempt (with the D4 ``post_check`` field),
   parses the output (``parse``), evaluates the plan through the bridge (``eval``), and ends with
   the pair's one ``query_result``, the resume key.
5. **The end.** With the real model, ``runs/ollama-server.log`` is scanned for ``truncating input
   prompt`` in the bytes written since this session started; any match fails the run (D4
   §Truncation, 3). Then the plans files are written from the stored outputs, and
   ``metrics.write_scores`` writes the per-plan files, the per-seed scores and ``metrics.json``.
   ``run_end`` closes the log and the manifest becomes ``succeeded``.

A hard error (``ContextOverflowError``, ``TruncationError``, ``TokenizerMismatchError``,
``ServerError``, a stack mismatch, ``EvaluationError``, ``AggregateMismatchError``, the log-scan
hit, or any bug) writes an ``error`` event with its traceback, then ``run_end`` and the manifest
say ``failed``. Ctrl-C ends the run as ``interrupted``. Both can be resumed (``resume.py``).

``rescore_run`` re-scores a finished run from its stored plans into ``rescore-<UTC ts>/`` and
compares every re-written file with the original byte for byte (D1 Phase 0 exit item 5, R1).
"""

import json
import platform
import subprocess
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from filelock import FileLock

from tripartite.config import (
    MODEL_LOCK_PATH,
    REPO_ROOT,
    RUNS_DIR,
    SERVER_LOG_PATH,
    RunConfig,
    StackConfig,
    config_hash,
    load_run_config,
    load_stack,
)
from tripartite.data.manifest import (
    DATABASE_ZIP,
    HF_FILES,
    HF_REVISION,
    N_VALIDATION,
    raw_dir,
    sha256_file,
)
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs, query_id_for
from tripartite.evaluation.aggregate import plan_pass
from tripartite.evaluation.bridge_client import VENDOR_DIR, EvaluatorBridge, bridge_from_env
from tripartite.evaluation.records import EvalRecord, load_eval_records
from tripartite.llm.calibration import (
    CALIBRATION_REPORT_PATH,
    Mode,
    require_valid_calibration,
)
from tripartite.llm.chat_template import ChatTemplate, template_from_env
from tripartite.llm.doctor import iogpu_wired_limit_mb, recommended_working_set_mb
from tripartite.llm.errors import DigestMismatchError, StackMismatchError, TruncationError
from tripartite.llm.fake_client import make_client
from tripartite.llm.ollama_client import GENERATE_ENDPOINT, LLMClient, OllamaClient, llm_mode
from tripartite.llm.tokenizer import Tokenizer, tokenizer_from_env
from tripartite.parse.text_plan_parser import PARSER_VERSION_ID, parse_plan, split_think
from tripartite.pipeline.lock import acquire_model_lock
from tripartite.pipeline.metrics import (
    METRICS_FILE,
    PlanRow,
    RunLogView,
    dump_json,
    evaluate_plan,
    load_run_log,
    plans_for,
    read_plans_file,
    result_from_event,
    score_files,
    write_plans_file,
    write_scores,
    write_text,
)
from tripartite.planner.prompt import PromptRenderer, RenderedPrompt, load_template
from tripartite.planner.sole_planner import AGENT_ID, PLANNER_ROLE, CallRecord, SolePlanner
from tripartite.runlog.reader import RunLogError, repair_tail
from tripartite.runlog.schema import (
    AgentInfo,
    DatasetInfo,
    EnvInfo,
    ErrorInfo,
    EvalResult,
    EvaluatorInfo,
    HardError,
    LlmCall,
    LlmRequest,
    Metrics,
    ModelInfo,
    ParseResult,
    Progress,
    QueryResult,
    QueryTotals,
    RunEnd,
    RunManifest,
    RunStage,
    RunStart,
    TimingMs,
    TokenCounts,
    new_run_id,
    validate_run_id,
)
from tripartite.runlog.writer import RunLogWriter, utc_now

MANIFEST_FILE: Final = "manifest.json"
EVENTS_FILE: Final = "events.jsonl"
BLOBS_DIR: Final = "blobs"
VENDOR_LOCK: Final = VENDOR_DIR / "VENDOR.lock"
TRUNCATION_MARKER: Final = "truncating input prompt"
"""What Ollama logs when it cuts a prompt to fit its context (F11, D4 §Truncation, 3)."""
FAKE_POST_CHECK_MODE: Final[Mode] = "total"
"""The fake client reports the whole prompt, so it is checked in mode ``total`` (D4)."""

Outcome = Literal["succeeded", "failed", "interrupted"]


class ResumeError(RuntimeError):
    """The run cannot be resumed: its status, config or stack does not allow it (D7)."""


class RescoreError(RuntimeError):
    """The run cannot be re-scored: it is not finished, or its inputs changed since."""


# --- dependencies --------------------------------------------------------------------------------


def _command(args: Sequence[str]) -> str | None:
    """The stripped stdout of a command run in the repository, or None if it failed."""
    try:
        proc = subprocess.run(
            list(args), cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def collect_env(stack: StackConfig, log_path: Path = SERVER_LOG_PATH) -> EnvInfo:
    """The ``run_start.env`` of this machine (D7): versions, locks, git state and hardware."""
    status = _command(["git", "status", "--porcelain"])
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        log = ""
    working_set_mb = recommended_working_set_mb(log)
    return EnvInfo(
        python=platform.python_version(),
        uv_lock_sha256=sha256_file(REPO_ROOT / "uv.lock"),
        evalenv_lock_sha256=sha256_file(REPO_ROOT / "evalenv" / "uv.lock"),
        git_commit=_command(["git", "rev-parse", "HEAD"]) or "unknown",
        git_dirty=bool(status) if status is not None else True,
        macos=platform.mac_ver()[0] or platform.platform(),
        chip=(
            _command(["sysctl", "-n", "machdep.cpu.brand_string"])
            or platform.processor()
            or platform.machine()
        ),
        ollama_env=dict(stack.runtime.env),
        iogpu_wired_limit_mb=iogpu_wired_limit_mb(),
        gpu_recommended_max_working_set_bytes=(
            None if working_set_mb is None else round(working_set_mb * 1e6)
        ),
    )


def check_server(stack: StackConfig, client: LLMClient) -> None:
    """After the warm-up: the running server must be the pinned one, so that the calibration
    describes it. ``/api/version`` must equal ``runtime.version``, and ``/api/ps`` must show
    exactly ``model.tag`` with the pinned digest and ``context_length == num_ctx``."""
    owned = not isinstance(client, OllamaClient)
    server = client if isinstance(client, OllamaClient) else OllamaClient(stack.runtime.url)
    try:
        version = server.version()
        if version != stack.runtime.version:
            raise StackMismatchError(
                f"the server runs Ollama {version}, but configs/stack.yaml pins "
                f"{stack.runtime.version}"
            )
        running = server.ps()
        names = [m.name for m in running]
        if names != [stack.model.tag]:
            raise StackMismatchError(f"expected exactly {stack.model.tag} loaded, found {names}")
        model = running[0]
        if model.digest.removeprefix("sha256:") != stack.digest_hex:
            raise DigestMismatchError(
                f"the loaded {stack.model.tag} has digest {model.digest}, but configs/stack.yaml "
                f"pins {stack.model.digest}; never update the pin"
            )
        if model.context_length is not None and model.context_length != stack.model.num_ctx:
            raise StackMismatchError(
                f"the loaded model's context length is {model.context_length}, not num_ctx "
                f"{stack.model.num_ctx}"
            )
    finally:
        if owned:
            server.close()


@dataclass
class RunDeps:
    """Where a run writes and what it talks to. The defaults are the CLI's; tests inject."""

    runs_dir: Path = RUNS_DIR
    lock_path: Path = MODEL_LOCK_PATH
    calibration_path: Path = CALIBRATION_REPORT_PATH
    server_log_path: Path = SERVER_LOG_PATH
    client: LLMClient | None = None
    """Default: ``make_client`` (the fake client or the dedicated server)."""
    tokenizer: Tokenizer | None = None
    """Default: ``tokenizer_from_env``."""
    chat: ChatTemplate | None = None
    """Default: ``template_from_env``."""
    bridge: EvaluatorBridge | None = None
    """Default: ``bridge_from_env``."""
    server_check: Callable[[StackConfig, LLMClient], None] = check_server
    env_probe: Callable[[StackConfig], EnvInfo] = collect_env
    clock: Callable[[], datetime] = utc_now
    sleep: Callable[[float], None] = time.sleep
    echo: Callable[[str], None] = lambda _line: None


# --- run_start -----------------------------------------------------------------------------------


def resolve_query_ids(config: RunConfig) -> list[str]:
    """The run's query ids in query_id order (D4): all 180 for ``queries: all``."""
    if config.queries == "all":
        return [query_id_for(i) for i in range(1, N_VALIDATION + 1)]
    return sorted(config.queries)


def model_info(stack: StackConfig, tokenizer: Tokenizer, mode: str) -> ModelInfo:
    """``run_start.model``. The tokenizer is the one that counts, so a fake run says
    ``fake-bytes@v1`` and ``runtime: "fake"`` and can never pass for a real one (D4)."""
    repo, _, revision = tokenizer.id.rpartition("@")
    return ModelInfo(
        runtime="fake" if mode == "fake" else stack.runtime.name,
        runtime_version=stack.runtime.version,
        tag=stack.model.tag,
        digest=stack.model.digest,
        quant=stack.model.quant,
        tokenizer_repo=repo,
        tokenizer_revision=revision,
    )


def evaluator_info() -> EvaluatorInfo:
    lock = json.loads(VENDOR_LOCK.read_text(encoding="utf-8"))
    return EvaluatorInfo(
        upstream_commit=lock["upstream"]["commit"], vendor_lock_sha256=sha256_file(VENDOR_LOCK)
    )


def dataset_info() -> DatasetInfo:
    """The dataset revision and the sha256 of the two files the loaders read."""
    return DatasetInfo(
        revision=HF_REVISION,
        files_sha256={name: sha256_file(raw_dir() / name) for name in HF_FILES},
    )


def run_start_payload(
    config: RunConfig,
    resolved: dict[str, Any],
    *,
    stack: StackConfig,
    tokenizer: Tokenizer,
    mode: str,
    query_ids: list[str],
    env: EnvInfo,
    resumed_from: str | None,
) -> RunStart:
    """``run_start`` (D7). ``resolved`` is the config as hashed (``RunConfig`` as JSON)."""
    return RunStart(
        kind=config.kind,
        mode=config.mode,
        context_mode=config.context_mode,
        split=config.split,
        query_ids=query_ids,
        seeds=list(config.seeds),
        order=config.order,
        config=resolved,
        config_hash=config_hash(resolved),
        model=model_info(stack, tokenizer, mode),
        prompt_version=config.prompt.version,
        prompt_sha256=config.prompt.sha256,
        parser_version=PARSER_VERSION_ID,
        evaluator=evaluator_info(),
        dataset=dataset_info(),
        database_zip_sha256=DATABASE_ZIP.sha256,
        env=env,
        agents=[AgentInfo(agent_id=AGENT_ID, role=PLANNER_ROLE, model_tag=stack.model.tag)],
        resumed_from=resumed_from,
    )


# --- the manifest --------------------------------------------------------------------------------


def read_manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / MANIFEST_FILE).read_bytes())


def write_manifest(run_dir: Path, manifest: RunManifest) -> None:
    """Rewrite ``manifest.json`` atomically (temp file plus ``os.replace``, D7)."""
    write_text(run_dir / MANIFEST_FILE, dump_json(manifest))


# --- the session ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResumeState:
    run_dir: Path
    manifest: RunManifest


@dataclass(eq=False)
class RunSession:
    """One process's work on one run: a fresh run, or one resume of it."""

    run_id: str
    run_dir: Path
    config: RunConfig
    stack: StackConfig
    mode: str
    post_check_mode: Mode
    query_ids: list[str]
    inputs: dict[str, PlannerInput]
    records: dict[str, EvalRecord]
    tokenizer: Tokenizer
    planner: SolePlanner
    client: LLMClient
    bridge: EvaluatorBridge
    writer: RunLogWriter
    manifest: RunManifest
    deps: RunDeps
    lock: FileLock
    log_offset: int | None
    """Size of the server log when this session started (real model only)."""
    done: set[tuple[str, int]] = field(default_factory=set)
    output_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    """call_id -> (visible, thinking) output tokens, by the local tokenizer."""
    owns_client: bool = False
    owns_bridge: bool = False

    @property
    def events_path(self) -> Path:
        return self.run_dir / EVENTS_FILE

    @property
    def seeds(self) -> list[int]:
        return list(self.config.seeds)

    @property
    def pairs(self) -> list[tuple[str, int]]:
        """Seed-major, in query_id order (D4)."""
        return [(query_id, seed) for seed in self.seeds for query_id in self.query_ids]

    def update(self, **changes: Any) -> None:
        """Change the manifest and rewrite it, validated and atomically."""
        data = {**self.manifest.model_dump(), **changes, "updated_at": self.deps.clock()}
        self.manifest = RunManifest.model_validate(data)
        write_manifest(self.run_dir, self.manifest)

    def set_stage(self, stage: RunStage) -> None:
        if self.manifest.stage != stage:
            self.update(stage=stage)


def _log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def open_run(config: RunConfig, deps: RunDeps, *, resume: ResumeState | None = None) -> RunSession:
    """Everything before the warm-up: checks, the model lock, and the run directory with its
    manifest and ``run_start`` (a new ``run_start`` with ``resumed_from`` when resuming)."""
    mode = llm_mode()
    stack = load_stack(config.stack_path)
    post_check_mode: Mode = FAKE_POST_CHECK_MODE
    if mode == "ollama":
        post_check_mode = require_valid_calibration(stack, deps.calibration_path).mode
    tokenizer = deps.tokenizer or tokenizer_from_env(stack)
    chat = deps.chat or template_from_env(stack)
    renderer = PromptRenderer(
        load_template(config.prompt_path, config.prompt.sha256), chat, config.prompt.version
    )
    query_ids = resolve_query_ids(config)
    inputs = {inp.query_id: inp for inp in load_planner_inputs(config.split)}
    records = {record.query_id: record for record in load_eval_records(config.split)}
    unknown = [query_id for query_id in query_ids if query_id not in inputs]
    if unknown:
        raise ValueError(f"unknown query ids {unknown}; expected val-001 … val-{N_VALIDATION}")

    lock = acquire_model_lock(deps.lock_path)
    try:
        if resume is None:
            created = _create(config, deps, stack, tokenizer, mode, query_ids)
            run_dir, manifest, writer, done = created
        else:
            run_dir, manifest, writer, done = _reopen(
                resume, config, deps, stack, tokenizer, mode, query_ids, post_check_mode
            )
        client = deps.client or make_client(stack, tokenizer, timeout_s=config.generation.timeout_s)
        bridge = deps.bridge or bridge_from_env()
    except BaseException:
        lock.release()
        raise
    planner = SolePlanner(
        client=client,
        tokenizer=tokenizer,
        renderer=renderer,
        stack=stack,
        generation=config.generation,
        post_check_mode=post_check_mode,
        sleep=deps.sleep,
    )
    return RunSession(
        run_id=run_dir.name,  # the directory's name is the run id (D7)
        run_dir=run_dir,
        config=config,
        stack=stack,
        mode=mode,
        post_check_mode=post_check_mode,
        query_ids=query_ids,
        inputs=inputs,
        records=records,
        tokenizer=tokenizer,
        planner=planner,
        client=client,
        bridge=bridge,
        writer=writer,
        manifest=manifest,
        deps=deps,
        lock=lock,
        log_offset=_log_size(deps.server_log_path) if mode == "ollama" else None,
        done=done,
        owns_client=deps.client is None,
        owns_bridge=deps.bridge is None,
    )


def _create(
    config: RunConfig,
    deps: RunDeps,
    stack: StackConfig,
    tokenizer: Tokenizer,
    mode: str,
    query_ids: list[str],
) -> tuple[Path, RunManifest, RunLogWriter, set[tuple[str, int]]]:
    resolved = config.model_dump(mode="json")
    now = deps.clock()
    run_id = new_run_id(config.kind, config_hash(resolved), now=now)
    payload = run_start_payload(
        config,
        resolved,
        stack=stack,
        tokenizer=tokenizer,
        mode=mode,
        query_ids=query_ids,
        env=deps.env_probe(stack),
        resumed_from=None,
    )
    run_dir = deps.runs_dir / run_id
    (run_dir / BLOBS_DIR).mkdir(parents=True)
    manifest = RunManifest(
        schema_version=1,
        run_start=payload,
        status="running",
        stage="generating",
        created_at=now,
        updated_at=now,
        finished_at=None,
        progress=Progress(done=0, total=len(query_ids) * len(config.seeds)),
        resumed=False,
        repaired_tail_bytes=0,
        metrics_path=None,
        error=None,
    )
    write_manifest(run_dir, manifest)
    writer = RunLogWriter(run_dir / EVENTS_FILE, run_id, clock=deps.clock)
    writer.write(payload)
    return run_dir, manifest, writer, set()


def _reopen(
    resume: ResumeState,
    config: RunConfig,
    deps: RunDeps,
    stack: StackConfig,
    tokenizer: Tokenizer,
    mode: str,
    query_ids: list[str],
    post_check_mode: Mode,
) -> tuple[Path, RunManifest, RunLogWriter, set[tuple[str, int]]]:
    """Resume (D7): repair a partial last line, check the log against today's stack, and append
    a new ``run_start`` with ``resumed_from``. Runs under the model lock."""
    run_dir, previous = resume.run_dir, resume.manifest
    run_id = run_dir.name
    events = run_dir / EVENTS_FILE
    repaired = repair_tail(events)
    view = load_run_log(events)
    first = view.run_start
    expected = model_info(stack, tokenizer, mode)
    problems = []
    if first.config_hash != config_hash(previous.run_start.config):
        problems.append("the stored config does not hash to the first run_start's config_hash")
    if first.model.model_dump() != expected.model_dump():
        problems.append(f"the stack differs: run {first.model.model_dump()}, now {expected}")
    if first.parser_version != PARSER_VERSION_ID:
        problems.append(f"parser {first.parser_version}, now {PARSER_VERSION_ID}")
    if first.prompt_sha256 != config.prompt.sha256:
        problems.append(f"prompt sha256 {first.prompt_sha256}, now {config.prompt.sha256}")
    if first.query_ids != query_ids or first.seeds != list(config.seeds):
        problems.append("the queries or seeds differ from the run's")
    if view.post_check_modes and view.post_check_modes != {post_check_mode}:
        problems.append(f"post-check mode {sorted(view.post_check_modes)}, now {post_check_mode}")
    if problems:
        raise ResumeError(f"run {run_id} cannot be resumed: " + "; ".join(problems))
    resolved = previous.run_start.config
    payload = run_start_payload(
        config,
        resolved,
        stack=stack,
        tokenizer=tokenizer,
        mode=mode,
        query_ids=query_ids,
        env=deps.env_probe(stack),
        resumed_from=run_id,
    )
    done = {pair for pair in view.query_results if pair[0] in query_ids}
    writer = RunLogWriter(events, run_id, clock=deps.clock)
    writer.write(payload)
    manifest = RunManifest.model_validate(
        {
            **previous.model_dump(),
            "run_start": payload.model_dump(),
            "status": "running",
            "stage": "generating",
            "updated_at": deps.clock(),
            "finished_at": None,
            "progress": Progress(done=len(done), total=len(query_ids) * len(config.seeds)),
            "resumed": True,
            "repaired_tail_bytes": repaired,
            "metrics_path": None,
            "error": None,
        }
    )
    write_manifest(run_dir, manifest)
    return run_dir, manifest, writer, done


# --- the calls, pair by pair ---------------------------------------------------------------------


def _store_blob(run_dir: Path, prompt: RenderedPrompt) -> None:
    """``blobs/<sha256>.txt``: each rendered prompt once, shared across seeds (D7)."""
    path = run_dir / BLOBS_DIR / f"{prompt.sha256}.txt"
    if not path.exists():
        write_text(path, prompt.text)


def _log_call(session: RunSession, call: CallRecord) -> None:
    """One ``llm_call`` event (D7) for one attempt, with the prompt stored in ``blobs/``."""
    _store_blob(session.run_dir, call.prompt)
    result = call.result
    thinking: str | None = None
    visible_tokens = thinking_tokens = 0
    if result is not None:
        visible, thinking = split_think(result.text)
        visible_tokens = session.tokenizer.count(visible)
        thinking_tokens = session.tokenizer.count(thinking) if thinking else 0
    session.output_counts[call.call_id] = (visible_tokens, thinking_tokens)
    options = call.request.options
    extra: dict[str, Any] = {}
    if call.post_check is not None:
        extra["post_check"] = call.post_check.as_event()
    session.writer.write(
        LlmCall(
            call_id=call.call_id,
            query_id=call.query_id,
            seed=call.seed,
            agent_id=AGENT_ID,
            role=call.role,
            round=None,
            parent_call_id=None,
            attempt=call.attempt,
            request=LlmRequest(
                endpoint=GENERATE_ENDPOINT,
                num_ctx=options.num_ctx,
                num_predict=options.num_predict,
                temperature=options.temperature,
                top_p=options.top_p,
                top_k=options.top_k,
                min_p=options.min_p,
                repeat_penalty=options.repeat_penalty,
                seed=options.seed,
                think=call.request.think,
                stop=list(options.stop),
            ),
            prompt_sha256=call.prompt.sha256,
            tokens=TokenCounts(
                input=call.prompt_tokens,
                input_reported=None if result is None else result.prompt_eval_count,
                input_cached_reported=None if result is None else result.prompt_eval_cached_count,
                output_visible=visible_tokens,
                output_thinking=thinking_tokens,
                output_reported=None if result is None else result.eval_count,
                tokenizer=session.tokenizer.id,
            ),
            timing_ms=TimingMs(
                load=None if result is None else result.load_ms,
                prefill=None if result is None else result.prefill_ms,
                generation=None if result is None else result.generation_ms,
                total_reported=None if result is None else result.total_ms,
                wall_client=call.wall_ms,
            ),
            done_reason=None if result is None else result.done_reason,
            output_text=None if result is None else result.text,
            thinking_text=thinking,
            error=(
                None
                if call.error is None
                else ErrorInfo(type=type(call.error).__name__, message=str(call.error))
            ),
            **extra,
        )
    )


def warm_up(session: RunSession) -> None:
    """D4's warm-up call, then (real model only) the check of the loaded model."""
    session.planner.warm_up(lambda call: _log_call(session, call))
    if session.mode == "ollama":
        session.deps.server_check(session.stack, session.client)


def _sum(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def run_one(session: RunSession, query_id: str, seed: int) -> QueryResult:
    """One (query, seed) pair: call, parse, evaluate, and its ``query_result`` (D3's
    ``pipeline.run_one``). Only the ``PlannerInput`` reaches the planner; the ``EvalRecord`` goes
    to the evaluator bridge alone."""
    inp = session.inputs[query_id]
    record = session.records[query_id]
    session.set_stage("generating")
    output = session.planner.plan(inp, seed, lambda call: _log_call(session, call))
    final = output.final

    parsed = None
    parse_ms = 0.0
    if output.text is not None:
        session.set_stage("parsing")
        start = time.perf_counter()
        parsed = parse_plan(output.text)
        parse_ms = (time.perf_counter() - start) * 1000
        session.writer.write(
            ParseResult(
                query_id=query_id,
                seed=seed,
                call_id=final.call_id,
                parser_version=PARSER_VERSION_ID,
                ok=parsed.ok,
                failure_reason=parsed.failure_reason,
                warnings=list(parsed.warnings),
                n_days=parsed.n_days,
                parse_ms=parse_ms,
            )
        )
    plan = None if parsed is None else parsed.plan

    session.set_stage("evaluating")
    result = evaluate_plan(session.bridge, record, plan)
    passed = plan_pass(result)
    session.writer.write(
        EvalResult(
            query_id=query_id,
            seed=seed,
            delivered=result.delivered,
            commonsense=result.commonsense,
            hard=result.hard,
            commonsense_pass=passed.commonsense,
            hard_pass=passed.hard,
            final_pass=passed.final,
        )
    )

    reason: str | None = None
    if parsed is None:
        reason = "llm_error"
    elif plan is None:
        length = final.result is not None and final.result.done_reason == "length"
        reason = "length_no_plan" if length else parsed.failure_reason
    counts = [session.output_counts.pop(call.call_id) for call in output.calls]
    results = [call.result for call in output.calls if call.result is not None]
    query_result = QueryResult(
        query_id=query_id,
        seed=seed,
        status="delivered" if plan is not None else "not_delivered",
        failure_reason=reason,
        totals=QueryTotals(
            input_tokens=sum(call.prompt_tokens for call in output.calls),
            output_tokens=sum(visible for visible, _ in counts),
            thinking_tokens=sum(thinking for _, thinking in counts),
            llm_calls=len(output.calls),
            wall_ms=sum(call.wall_ms for call in output.calls) + parse_ms,
            prefill_ms=_sum([r.prefill_ms for r in results]),
            generation_ms=_sum([r.generation_ms for r in results]),
            load_ms=_sum([r.load_ms for r in results]),
            parse_ms=parse_ms,
        ),
    )
    session.writer.write(query_result)
    session.done.add((query_id, seed))
    session.update(progress=Progress(done=len(session.done), total=len(session.pairs)))
    return query_result


# --- the end of a run ----------------------------------------------------------------------------


def scan_server_log(path: Path, offset: int) -> list[str]:
    """The lines with ``truncating input prompt`` written to the server log since ``offset``
    (the whole log if it has since shrunk)."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise TruncationError(
            f"{path} is missing, so the truncation scan cannot run (D4 §Truncation, 3)"
        ) from None
    tail = data[offset:] if len(data) >= offset else data
    text = tail.decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if TRUNCATION_MARKER in line]


def _counts(session: RunSession, view: RunLogView | None) -> dict[str, int]:
    """``run_end.counts`` over the whole log, resumed sessions included (D7)."""
    pairs = session.pairs
    found = {} if view is None else view.query_results
    results = [found[pair] for pair in pairs if pair in found]
    return {
        "queries": len(session.query_ids),
        "seeds": len(session.seeds),
        "pairs_total": len(pairs),
        "pairs_done": len(results) if view is not None else len(session.done),
        "delivered": sum(r.status == "delivered" for r in results),
        "llm_calls": 0 if view is None else view.llm_calls,
        "errors": 0 if view is None else view.errors,
    }


def _plan_rows(session: RunSession, view: RunLogView) -> dict[int, list[PlanRow]]:
    queries = {query_id: session.inputs[query_id].query for query_id in session.query_ids}
    return {seed: plans_for(view, seed, session.query_ids, queries) for seed in session.seeds}


def finish_run(session: RunSession) -> Metrics:
    """The truncation scan, the plans files, the scores and ``run_end`` (D4, D5, D7)."""
    if session.log_offset is not None:
        hits = scan_server_log(session.deps.server_log_path, session.log_offset)
        if hits:
            raise TruncationError(
                f"{len(hits)} '{TRUNCATION_MARKER}' line(s) in the server log since this run "
                f"started (D4 §Truncation, 3), the first: {hits[0]}"
            )
    session.set_stage("evaluating")
    finished_at = session.deps.clock()
    view = load_run_log(session.events_path)
    plans_paths = {}
    for seed, rows in _plan_rows(session, view).items():
        plans_paths[seed] = session.run_dir / f"plans_seed{seed}.jsonl"
        write_plans_file(plans_paths[seed], rows)
    results_by_seed = {}
    for seed in session.seeds:
        missing = [q for q in session.query_ids if (q, seed) not in view.evals]
        if missing:
            raise RunLogError(f"seed {seed}: no eval event for {missing}")
        results_by_seed[seed] = [
            result_from_event(view.evals[(query_id, seed)]) for query_id in session.query_ids
        ]
    metrics = write_scores(
        session.run_dir,
        view=view,
        run_id=session.run_id,
        kind=session.config.kind,
        config_hash=view.run_start.config_hash,
        query_ids=session.query_ids,
        seeds=session.seeds,
        results_by_seed=results_by_seed,
        plans_paths=plans_paths,
        records=session.records,
        bridge=session.bridge,
        created_at=session.manifest.created_at,
        finished_at=finished_at,
    )
    session.writer.write(
        RunEnd(
            status="succeeded",
            counts=_counts(session, view),
            metrics_path=METRICS_FILE,
            error=None,
        )
    )
    session.update(
        status="succeeded",
        stage="done",
        finished_at=finished_at,
        metrics_path=METRICS_FILE,
        error=None,
    )
    return metrics


def _end(session: RunSession, status: Literal["failed", "interrupted"], error: ErrorInfo) -> None:
    """``run_end`` and the manifest for a run that did not succeed."""
    try:
        view: RunLogView | None = load_run_log(session.events_path)
    except (RunLogError, OSError):
        view = None
    session.writer.write(
        RunEnd(status=status, counts=_counts(session, view), metrics_path=None, error=error)
    )
    session.update(status=status, finished_at=session.deps.clock(), error=error)


def close_run(session: RunSession) -> None:
    """Release what the session holds: the bridge, the log, the client and the model lock."""
    try:
        if session.owns_bridge:
            session.bridge.close()
        session.writer.close()
        if session.owns_client and isinstance(session.client, OllamaClient):
            session.client.close()
    finally:
        session.lock.release()


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    run_dir: Path
    status: Outcome
    metrics: Metrics | None
    error: ErrorInfo | None


def _progress_line(index: int, total: int, result: QueryResult) -> str:
    reason = f" ({result.failure_reason})" if result.failure_reason else ""
    return (
        f"run: [{index}/{total}] {result.query_id} seed {result.seed}: {result.status}{reason}, "
        f"wall {result.totals.wall_ms / 1000:.1f} s, {result.totals.llm_calls} call(s)"
    )


def execute(session: RunSession) -> RunOutcome:
    """The warm-up, every pair still to do, and the end of the run, with D7's error handling.
    Always releases the session."""
    try:
        try:
            warm_up(session)
            pairs = session.pairs
            for index, (query_id, seed) in enumerate(pairs, start=1):
                if (query_id, seed) in session.done:
                    continue
                result = run_one(session, query_id, seed)
                session.deps.echo(_progress_line(index, len(pairs), result))
            metrics = finish_run(session)
        except KeyboardInterrupt:
            error = ErrorInfo(type="KeyboardInterrupt", message="interrupted; resume the run")
            _end(session, "interrupted", error)
            return RunOutcome(session.run_id, session.run_dir, "interrupted", None, error)
        except Exception as exc:
            error = ErrorInfo(type=type(exc).__name__, message=str(exc))
            session.writer.write(
                HardError(type=error.type, message=error.message, traceback=traceback.format_exc())
            )
            _end(session, "failed", error)
            return RunOutcome(session.run_id, session.run_dir, "failed", None, error)
        return RunOutcome(session.run_id, session.run_dir, "succeeded", metrics, None)
    finally:
        close_run(session)


def start_run(config_path: Path, deps: RunDeps | None = None) -> RunOutcome:
    """``tripartite run start --config <path>``."""
    deps = deps or RunDeps()
    return execute(open_run(load_run_config(config_path), deps))


# --- rescore (D1 Phase 0 exit item 5, R1) --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RescoreReport:
    out_dir: Path
    compared: list[str]
    mismatches: list[str]
    """One message per file that differs, naming it."""

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _difference(name: str, original: bytes, rescored: bytes) -> str:
    for number, (a, b) in enumerate(
        zip(original.splitlines(), rescored.splitlines(), strict=False), start=1
    ):
        if a != b:
            return f"{name}: line {number} differs"
    return f"{name}: {len(original)} bytes in the run, {len(rescored)} re-scored"


def rescore_run(
    run_id: str,
    *,
    runs_dir: Path = RUNS_DIR,
    bridge: EvaluatorBridge | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> RescoreReport:
    """Re-score a finished run from its stored ``plans_seed*.jsonl`` into
    ``runs/<run_id>/rescore-<UTC ts>/`` with the code that scored it, and compare every re-written
    file with the original byte for byte (R1). Never calls the model, never re-parses."""
    run_dir = runs_dir / validate_run_id(run_id)
    try:
        manifest = read_manifest(run_dir)
    except FileNotFoundError:
        raise RescoreError(f"no run {run_id} in {runs_dir}") from None
    if manifest.status != "succeeded" or manifest.finished_at is None:
        raise RescoreError(f"run {run_id} is {manifest.status}; only a succeeded run is scored")
    view = load_run_log(run_dir / EVENTS_FILE)
    start = view.run_start
    if dataset_info().files_sha256 != start.dataset.files_sha256:
        raise RescoreError("the dataset files differ from the ones the run used")
    if sha256_file(VENDOR_LOCK) != start.evaluator.vendor_lock_sha256:
        raise RescoreError("vendor/travelplanner/VENDOR.lock differs from the run's")
    records = {record.query_id: record for record in load_eval_records(start.split)}
    out_dir = run_dir / f"rescore-{clock():%Y%m%dT%H%M%SZ}"
    out_dir.mkdir()
    bridge_in_use = bridge or bridge_from_env()
    try:
        results_by_seed = {}
        plans_paths = {}
        for seed in start.seeds:
            plans_paths[seed] = run_dir / f"plans_seed{seed}.jsonl"
            rows = read_plans_file(plans_paths[seed])
            if [row.query_id for row in rows] != start.query_ids:
                raise RescoreError(f"{plans_paths[seed].name} does not list the run's queries")
            results_by_seed[seed] = [
                evaluate_plan(bridge_in_use, records[row.query_id], row.plan) for row in rows
            ]
        write_scores(
            out_dir,
            view=view,
            run_id=run_id,
            kind=start.kind,
            config_hash=start.config_hash,
            query_ids=start.query_ids,
            seeds=start.seeds,
            results_by_seed=results_by_seed,
            plans_paths=plans_paths,
            records=records,
            bridge=bridge_in_use,
            created_at=manifest.created_at,
            finished_at=manifest.finished_at,
        )
    finally:
        if bridge is None:
            bridge_in_use.close()
    compared = score_files(start.seeds)
    mismatches = []
    for name in compared:
        original = run_dir / name
        if not original.exists():
            mismatches.append(f"{name}: missing from the run directory")
            continue
        a, b = original.read_bytes(), (out_dir / name).read_bytes()
        if a != b:
            mismatches.append(_difference(name, a, b))
    return RescoreReport(out_dir, compared, mismatches)
