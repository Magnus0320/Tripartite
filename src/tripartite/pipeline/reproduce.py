"""``tripartite run reproduce-check``: R1, R2 and R3 between two runs (ARCHITECTURE.md D1
§Definition of "reproducible", D9 §M5a: ``reproduce-check``).

``reproduce_check(run_a, run_b)`` reads two succeeded runs and:

1. **Preconditions** (``PreconditionError``; nothing is written). Both runs exist, are
   ``succeeded`` and are different runs, with equal ``config_hash``, equal stack pins
   (``run_start.model``, ``run_start.env.ollama_env`` and the one ``num_ctx`` their calls sent),
   equal prompt sha256, parser version and calibrated post-check mode. Their first
   ``run_start.env.git_commit`` must be equal unless ``allow_different_commit``, which is for
   diagnostics only. The dataset files and ``VENDOR.lock`` must be the runs' own, and each plans
   file must hold one line per query.
2. **R1, re-scoring (exact).** Each run goes through ``run.rescore_run``, the ``make eval`` path,
   into its own ``rescore-<ts>/``. Every file it re-writes (``per_plan_eval_seed{n}.jsonl`` and
   ``metrics_seed{n}.json`` per seed, plus ``metrics.json``) must equal the original byte for
   byte. The plans files are its input; R2 checks them.
3. **R2, re-parsing (exact).** For each pair with a ``query_result``, the ``output_text`` of its
   last successful call is parsed again with the current parser, and the line the pipeline would
   write to ``plans_seed{n}.jsonl`` is rebuilt and compared byte for byte with the stored one,
   as is the failure reason. A pair that ended as ``llm_error`` has no output: skipped, counted.
4. **R3, regeneration (tolerance).** For each official metric, the two runs' means over seeds
   (``metrics.json``) differ by at most 2.0 percentage points (plus 1e-9 for float noise).
5. **Identity (a diagnostic, no threshold).** For each pair with an output in both runs, whether
   the two outputs are byte-identical: overall, per seed, and for each seed's first call.

The result is ``runs/reproduce/<run_a>__<run_b>/reproduce_check.json``, outside both run
directories (D7). It holds run ids, commits, hashes, query ids, seeds, file names and numbers,
never plan or output text, so it can be committed (§8).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from tripartite.config import RUNS_DIR
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.bridge_client import EvaluatorBridge
from tripartite.parse.text_plan_parser import parse_plan
from tripartite.pipeline.metrics import (
    METRIC_KEYS,
    METRICS_FILE,
    Pair,
    PlanRow,
    RunLogView,
    load_run_log,
    plans_line,
    query_index,
    write_text,
)
from tripartite.pipeline.run import (
    EVENTS_FILE,
    RescoreError,
    current_git_commit,
    failure_reason_for,
    read_manifest,
    require_scoring_inputs,
    rescore_run,
)
from tripartite.runlog.reader import RunLogError
from tripartite.runlog.schema import (
    Metrics,
    OfficialMetric,
    RunManifest,
    RunStartEvent,
    UtcDatetime,
    validate_run_id,
)
from tripartite.runlog.writer import utc_now

TOLERANCE_PP: Final = 2.0
"""R3: how far apart two runs' means may be, in percentage points (D1)."""
SLACK_PP: Final = 1e-9
"""Float noise allowed on top of ``TOLERANCE_PP``."""
REPRODUCE_DIR: Final = "reproduce"
REPORT_FILE: Final = "reproduce_check.json"
LLM_ERROR: Final = "llm_error"


class PreconditionError(RuntimeError):
    """The two runs cannot be compared (exit 2; nothing is written)."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


# --- reproduce_check.json ------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class RunRef(_Model):
    run_id: str
    git_commit: str
    config_hash: str
    allow_dirty: bool
    resumed: bool
    subset: bool
    n_queries: int
    seeds: list[int]


class Preconditions(_Model):
    same_config_hash: Literal[True] = True
    same_stack: Literal[True] = True
    same_prompt: Literal[True] = True
    same_parser: Literal[True] = True
    same_mode: Literal[True] = True
    same_git_commit: bool


class R1Run(_Model):
    files_compared: int
    mismatched: list[str]


class R1(_Model):
    passed: bool = Field(alias="pass")
    per_run: dict[str, R1Run]


class PairRef(_Model):
    query_id: str
    seed: int


class R2Run(_Model):
    pairs_checked: int
    pairs_skipped_llm_error: int
    mismatched: list[PairRef]


class R2(_Model):
    passed: bool = Field(alias="pass")
    per_run: dict[str, R2Run]


class R3Metric(_Model):
    mean_a: float
    mean_b: float
    diff_pp: float
    passed: bool = Field(alias="pass")


class R3(_Model):
    passed: bool = Field(alias="pass")
    tolerance_pp: float
    metrics: dict[OfficialMetric, R3Metric]


class Count(_Model):
    identical: int
    total: int
    fraction: float


class Identity(_Model):
    overall: Count
    per_seed: dict[str, Count]
    first_call: dict[str, bool]


class RunRefs(_Model):
    a: RunRef
    b: RunRef


class ReproduceCheck(_Model):
    """``reproduce_check.json`` (D9 §M5a)."""

    schema_version: Literal[1]
    created_at: UtcDatetime
    tool_git_commit: str
    runs: RunRefs
    preconditions: Preconditions
    r1: R1
    r2: R2
    r3: R3
    identity: Identity
    warnings: list[str]
    passed: bool = Field(alias="pass")


def dump_check(check: ReproduceCheck) -> str:
    """Whole-file JSON as ``metrics.dump_json`` writes it, with the schema's ``pass`` keys."""
    return check.model_dump_json(indent=2, by_alias=True) + "\n"


@dataclass(frozen=True, slots=True)
class ReproduceReport:
    check: ReproduceCheck
    path: Path

    @property
    def exit_code(self) -> int:
        """0 when R1, R2 and R3 all pass, else 1 (warnings never change it)."""
        return 0 if self.check.passed else 1


# --- the two runs --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadedRun:
    run_id: str
    run_dir: Path
    manifest: RunManifest
    view: RunLogView
    metrics: Metrics

    @property
    def start(self) -> RunStartEvent:
        """The run's first ``run_start``: what it was started with."""
        return self.view.run_start

    @property
    def allow_dirty(self) -> bool:
        return any(getattr(start, "allow_dirty", False) is True for start in self.view.run_starts)

    @property
    def sessions(self) -> int:
        return len(self.view.run_starts)

    @property
    def resumed(self) -> bool:
        return self.manifest.resumed or self.sessions > 1

    @property
    def pairs(self) -> list[Pair]:
        """Seed-major, in the run's query order (D4)."""
        return [(query_id, seed) for seed in self.start.seeds for query_id in self.start.query_ids]

    def plans_path(self, seed: int) -> Path:
        return self.run_dir / f"plans_seed{seed}.jsonl"

    def plans_lines(self, seed: int) -> list[bytes]:
        """The stored plans file of ``seed`` as its lines, without their LF."""
        return self.plans_path(seed).read_bytes().split(b"\n")[:-1]

    def output(self, pair: Pair) -> str | None:
        """The output that produced the pair's plan, or None when no call gave one."""
        call = self.view.outputs.get(pair)
        return None if call is None else call.output_text

    def ref(self) -> RunRef:
        return RunRef(
            run_id=self.run_id,
            git_commit=self.start.env.git_commit,
            config_hash=self.start.config_hash,
            allow_dirty=self.allow_dirty,
            resumed=self.resumed,
            subset=self.metrics.subset,
            n_queries=self.metrics.n_queries,
            seeds=list(self.metrics.seeds),
        )


def load_run(run_id: str, runs_dir: Path) -> LoadedRun:
    """A succeeded run, read with the strict reader (D7). ``PreconditionError`` otherwise."""
    try:
        validate_run_id(run_id)
    except ValueError:
        raise PreconditionError([f"{run_id!r} is not a run id"]) from None
    run_dir = runs_dir / run_id
    try:
        manifest = read_manifest(run_dir)
    except FileNotFoundError:
        raise PreconditionError([f"no run {run_id} in {runs_dir}"]) from None
    if manifest.status != "succeeded":
        raise PreconditionError(
            [f"run {run_id} is {manifest.status}; only succeeded runs are compared"]
        )
    view = load_run_log(run_dir / EVENTS_FILE)
    metrics = Metrics.model_validate_json((run_dir / METRICS_FILE).read_bytes())
    run = LoadedRun(run_id, run_dir, manifest, view, metrics)
    for seed in run.start.seeds:
        data = run.plans_path(seed).read_bytes()
        if not data.endswith(b"\n") or data.count(b"\n") != len(run.start.query_ids):
            raise PreconditionError(
                [f"run {run_id}: {run.plans_path(seed).name} does not hold one line per query"]
            )
    return run


def _single_num_ctx(run: LoadedRun, problems: list[str]) -> int | None:
    if len(run.view.num_ctxs) != 1:
        problems.append(
            f"run {run.run_id} sent num_ctx {sorted(run.view.num_ctxs)}; expected exactly one"
        )
        return None
    return next(iter(run.view.num_ctxs))


def check_preconditions(
    a: LoadedRun, b: LoadedRun, *, allow_different_commit: bool
) -> Preconditions:
    """D9 §M5a preconditions between two loaded runs. Every unmet one is named."""
    start_a, start_b = a.start, b.start
    problems: list[str] = []
    if a.run_id == b.run_id:
        problems.append(f"--run and --run2 name the same run {a.run_id}")
    if start_a.config_hash != start_b.config_hash:
        problems.append(f"config_hash differs: {start_a.config_hash} vs {start_b.config_hash}")
    model_a, model_b = start_a.model.model_dump(), start_b.model.model_dump()
    for key in model_a.keys() | model_b.keys():
        if model_a.get(key) != model_b.get(key):
            problems.append(
                f"the stack differs: model.{key} {model_a.get(key)!r} vs {model_b.get(key)!r}"
            )
    if start_a.env.ollama_env != start_b.env.ollama_env:
        problems.append(
            f"the stack differs: runtime.env {start_a.env.ollama_env} vs {start_b.env.ollama_env}"
        )
    num_ctx_a, num_ctx_b = _single_num_ctx(a, problems), _single_num_ctx(b, problems)
    if num_ctx_a is not None and num_ctx_b is not None and num_ctx_a != num_ctx_b:
        problems.append(f"the stack differs: num_ctx {num_ctx_a} vs {num_ctx_b}")
    if start_a.prompt_sha256 != start_b.prompt_sha256:
        problems.append(
            f"prompt sha256 differs: {start_a.prompt_sha256} vs {start_b.prompt_sha256}"
        )
    if start_a.parser_version != start_b.parser_version:
        problems.append(
            f"parser version differs: {start_a.parser_version} vs {start_b.parser_version}"
        )
    if a.view.post_check_mode != b.view.post_check_mode:
        problems.append(
            f"calibrated mode differs: {a.view.post_check_mode} vs {b.view.post_check_mode}"
        )
    same_commit = start_a.env.git_commit == start_b.env.git_commit
    if not same_commit and not allow_different_commit:
        problems.append(
            f"git_commit differs: {start_a.env.git_commit} vs {start_b.env.git_commit}; "
            "--allow-different-commit compares them anyway, for diagnostics only"
        )
    if problems:
        raise PreconditionError(sorted(problems))
    return Preconditions(same_git_commit=same_commit)


# --- R1, R2, R3 and the identity diagnostic ------------------------------------------------------


def check_r1(
    runs: Sequence[LoadedRun],
    *,
    runs_dir: Path,
    bridge: EvaluatorBridge | None,
    clock: Callable[[], datetime],
) -> R1:
    """Re-score each run through ``rescore_run`` (the ``make eval`` path) and compare."""
    per_run = {}
    for run in runs:
        report = rescore_run(run.run_id, runs_dir=runs_dir, bridge=bridge, clock=clock)
        per_run[run.run_id] = R1Run(
            files_compared=len(report.compared), mismatched=report.mismatched_names
        )
    return R1(passed=not any(r.mismatched for r in per_run.values()), per_run=per_run)


def check_r2(run: LoadedRun, queries: dict[str, str]) -> R2Run:
    """Re-parse every stored output of ``run`` and rebuild its plans lines. ``queries`` maps a
    query id to its query text, the planner-visible field each plans line carries."""
    checked = skipped = 0
    mismatched = []
    for seed in run.start.seeds:
        stored = run.plans_lines(seed)
        for line, query_id in zip(stored, run.start.query_ids, strict=True):
            pair = (query_id, seed)
            result = run.view.query_results.get(pair)
            if result is None:
                raise RunLogError(f"run {run.run_id}: no query_result for {pair}")
            if result.failure_reason == LLM_ERROR:
                skipped += 1
                continue
            call = run.view.outputs.get(pair)
            if call is None or call.output_text is None:
                raise RunLogError(f"run {run.run_id}: no stored output for {pair}")
            parsed = parse_plan(call.output_text)
            rebuilt = plans_line(PlanRow(query_index(query_id), queries[query_id], parsed.plan))
            reason = failure_reason_for(parsed, call.done_reason)
            checked += 1
            if rebuilt.encode("utf-8") != line or reason != result.failure_reason:
                mismatched.append(PairRef(query_id=query_id, seed=seed))
    return R2Run(pairs_checked=checked, pairs_skipped_llm_error=skipped, mismatched=mismatched)


def check_r3(metrics_a: Metrics, metrics_b: Metrics) -> R3:
    """Each official metric's mean over seeds, run a against run b."""
    metrics = {}
    for key in METRIC_KEYS:
        mean_a, mean_b = metrics_a.metrics[key].mean, metrics_b.metrics[key].mean
        diff_pp = abs(mean_a - mean_b) * 100
        metrics[key] = R3Metric(
            mean_a=mean_a, mean_b=mean_b, diff_pp=diff_pp, passed=diff_pp <= TOLERANCE_PP + SLACK_PP
        )
    return R3(
        passed=all(m.passed for m in metrics.values()), tolerance_pp=TOLERANCE_PP, metrics=metrics
    )


def _count(flags: Sequence[bool]) -> Count:
    identical, total = sum(flags), len(flags)
    return Count(identical=identical, total=total, fraction=identical / total if total else 0.0)


def identity(a: LoadedRun, b: LoadedRun) -> Identity:
    """Which pairs have byte-identical outputs in both runs. A pair without an output in either
    run is not counted, and as a seed's first call it reports false."""
    same: dict[Pair, bool] = {}
    for pair in a.pairs:
        out_a, out_b = a.output(pair), b.output(pair)
        if out_a is not None and out_b is not None:
            same[pair] = out_a.encode("utf-8") == out_b.encode("utf-8")
    seeds = a.start.seeds
    first = a.start.query_ids[0]
    return Identity(
        overall=_count(list(same.values())),
        per_seed={
            str(seed): _count([flag for pair, flag in same.items() if pair[1] == seed])
            for seed in seeds
        },
        first_call={str(seed): same.get((first, seed), False) for seed in seeds},
    )


def warnings_for(a: LoadedRun, b: LoadedRun, *, allow_different_commit: bool) -> list[str]:
    """What a reader must know before using the result; never changes the exit code."""
    warnings = []
    for run in (a, b):
        if run.allow_dirty:
            warnings.append(f"run {run.run_id} has allow_dirty: true in a run_start")
        if run.resumed:
            warnings.append(f"run {run.run_id} was resumed ({run.sessions} sessions)")
        if run.manifest.repaired_tail_bytes > 0:
            warnings.append(
                f"run {run.run_id} has repaired_tail_bytes {run.manifest.repaired_tail_bytes}"
            )
    if allow_different_commit:
        warnings.append(
            "--allow-different-commit was used "
            f"({a.start.env.git_commit} vs {b.start.env.git_commit}): diagnostics only, never "
            "the Phase 1 exit"
        )
    for run in (a, b):
        if run.metrics.subset:
            warnings.append(
                f"run {run.run_id} is a subset run (n_queries {run.metrics.n_queries}), "
                "not a result"
            )
    return warnings


# --- the command ---------------------------------------------------------------------------------


def report_path(run_a: str, run_b: str, runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / REPRODUCE_DIR / f"{run_a}__{run_b}" / REPORT_FILE


def reproduce_check(
    run_a: str,
    run_b: str,
    *,
    allow_different_commit: bool = False,
    runs_dir: Path = RUNS_DIR,
    bridge: EvaluatorBridge | None = None,
    clock: Callable[[], datetime] = utc_now,
    git_commit: Callable[[], str] = current_git_commit,
) -> ReproduceReport:
    """``tripartite run reproduce-check --run <a> --run2 <b> [--allow-different-commit]``.
    Never calls the model. Raises before anything is written when the runs cannot be compared."""
    a, b = load_run(run_a, runs_dir), load_run(run_b, runs_dir)
    preconditions = check_preconditions(a, b, allow_different_commit=allow_different_commit)
    try:
        require_scoring_inputs(a.start)
        require_scoring_inputs(b.start)
    except RescoreError as exc:
        raise PreconditionError([str(exc)]) from None
    queries = {inp.query_id: inp.query for inp in load_planner_inputs(a.start.split)}
    unknown = [query_id for query_id in a.start.query_ids if query_id not in queries]
    if unknown:
        raise PreconditionError([f"the data has no query {unknown}"])

    r1 = check_r1((a, b), runs_dir=runs_dir, bridge=bridge, clock=clock)
    per_run_r2 = {run.run_id: check_r2(run, queries) for run in (a, b)}
    r2 = R2(passed=not any(r.mismatched for r in per_run_r2.values()), per_run=per_run_r2)
    r3 = check_r3(a.metrics, b.metrics)
    check = ReproduceCheck(
        schema_version=1,
        created_at=clock(),
        tool_git_commit=git_commit(),
        runs=RunRefs(a=a.ref(), b=b.ref()),
        preconditions=preconditions,
        r1=r1,
        r2=r2,
        r3=r3,
        identity=identity(a, b),
        warnings=warnings_for(a, b, allow_different_commit=allow_different_commit),
        passed=r1.passed and r2.passed and r3.passed,
    )
    path = report_path(run_a, run_b, runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, dump_check(check))
    return ReproduceReport(check, path)


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _fraction(count: Count) -> str:
    return f"{count.identical}/{count.total} ({count.fraction:.4f})"


def format_report(report: ReproduceReport) -> list[str]:
    """What the CLI prints: the three checks, the R3 table, the identity fractions, every
    warning and the output path. Numbers and ids only."""
    check = report.check
    r1 = "; ".join(
        f"{run_id}: {r.files_compared} files compared, "
        + (f"mismatched {r.mismatched}" if r.mismatched else "all byte-identical")
        for run_id, r in check.r1.per_run.items()
    )
    r2 = "; ".join(
        f"{run_id}: {r.pairs_checked} pairs checked, {r.pairs_skipped_llm_error} skipped "
        f"(llm_error), {len(r.mismatched)} mismatched"
        + "".join(f" [{p.query_id} seed {p.seed}]" for p in r.mismatched)
        for run_id, r in check.r2.per_run.items()
    )
    failed = [key for key, m in check.r3.metrics.items() if not m.passed]
    lines = [
        f"R1 {_verdict(check.r1.passed)} (re-scoring): {r1}",
        f"R2 {_verdict(check.r2.passed)} (re-parsing): {r2}",
        f"R3 {_verdict(check.r3.passed)} (regeneration, tolerance {check.r3.tolerance_pp} pp): "
        + (f"outside tolerance: {failed}" if failed else "all six means within tolerance"),
        f"{'metric':<40} {'mean_a':>10} {'mean_b':>10} {'diff_pp':>9}",
    ]
    lines += [
        f"{key:<40} {m.mean_a:>10.6f} {m.mean_b:>10.6f} {m.diff_pp:>9.4f} {_verdict(m.passed)}"
        for key, m in check.r3.metrics.items()
    ]
    lines.append(f"identity overall: {_fraction(check.identity.overall)}")
    lines += [
        f"identity seed {seed}: {_fraction(count)}"
        for seed, count in check.identity.per_seed.items()
    ]
    lines.append(
        "identity first calls: "
        + ", ".join(
            f"seed {seed} {'identical' if same else 'not identical'}"
            for seed, same in check.identity.first_call.items()
        )
    )
    lines += [f"WARNING: {warning}" for warning in check.warnings]
    lines.append(f"{_verdict(check.passed)}: wrote {report.path}")
    return lines
