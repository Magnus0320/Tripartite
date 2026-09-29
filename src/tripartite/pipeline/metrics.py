"""Scoring a run, and the files it writes (ARCHITECTURE.md D5, D7, D1 R1).

A run's scores are computed by ``write_scores``, and only there. The run calls it once every pair
is done; ``tripartite run rescore`` calls it again on the stored plans (D1 Phase 0 exit item 5),
so R1 compares one code path with itself. For each seed it writes:

- ``per_plan_eval_seed{n}.jsonl``: the evaluator's verdict on each plan, in plans-file order, one
  ``{"idx", "query_id", "delivered", "commonsense", "hard"}`` object per line, each group as
  ``{check: [value, message]}`` in ``eval.py``'s ``key_dict`` order, or null;
- ``metrics_seed{n}.json``: the six official scores. A subset run uses ``aggregate()``
  (``source: "subset_aggregate"``). A full 180-query run uses the bridge's own ``aggregate`` op,
  which runs ``eval_score`` itself (``source: "official_eval_score"``), and ``aggregate()`` must
  agree with it to 1e-12 or ``AggregateMismatchError`` aborts the run (D5);

and then ``metrics.json``: per-seed values, mean and sample SD of the six scores, the
non-delivery breakdown, the parse summary, and token and latency statistics over the
per-(query, seed) ``query_result`` totals, warm-ups excluded (D7). ``created_at`` and
``finished_at`` are passed in (the manifest's values), so a rescore reproduces them byte for
byte.

``load_run_log`` reads ``events.jsonl`` with the strict reader. A pair's plan is re-parsed from
the stored output of its last successful call (``plans_for``), so the plans file is derived from
the raw outputs by the deterministic parser (R2) and checked against the ``parse`` events.

All JSON is written deterministically: files are UTF-8 with LF line ends, JSON Lines use
``json.dumps(obj, ensure_ascii=False)``, and whole-file JSON is indented by 2 with a final
newline.
"""

import json
import os
import statistics
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel

from tripartite.data.manifest import N_VALIDATION
from tripartite.data.planner_inputs import query_id_for
from tripartite.evaluation.aggregate import OfficialScores, aggregate
from tripartite.evaluation.bridge_client import EvaluatorBridge, Plan
from tripartite.evaluation.constraints import (
    COMMONSENSE_KEYS,
    HARD_KEYS,
    ConstraintGroup,
    PerPlanResult,
)
from tripartite.evaluation.records import EvalRecord, write_bridge_records
from tripartite.llm.context import nearest_rank_p95
from tripartite.parse.text_plan_parser import parse_plan
from tripartite.planner.sole_planner import WARMUP_ROLE
from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.schema import (
    ErrorEvent,
    EvalEvent,
    LatencyStats,
    LlmCallEvent,
    Metrics,
    MetricsSeed,
    MetricSummary,
    OfficialMetric,
    ParseEvent,
    ParseSummary,
    QueryResultEvent,
    RunKind,
    RunStartEvent,
    Stats,
    TokenStats,
)

AGGREGATE_TOLERANCE: Final = 1e-12
"""How far ``aggregate()`` may be from the official ``eval_score`` on a full run (D5)."""
NON_DELIVERY_REASONS: Final = (
    "llm_error",
    "empty_output",
    "length_no_plan",
    "no_day_blocks",
    "no_fields",
)
"""D2's non-delivery reasons; ``metrics.json`` always lists all five, zeros included."""
METRICS_FILE: Final = "metrics.json"
METRIC_KEYS: Final[tuple[OfficialMetric, ...]] = get_args(OfficialMetric)
"""The six official keys, verbatim and in ``eval.py``'s order."""

Source = Literal["official_eval_score", "subset_aggregate"]
Pair = tuple[str, int]


class AggregateMismatchError(RuntimeError):
    """``aggregate()`` and the official ``eval_score`` disagree on a full run (D5)."""


# --- the run log ---------------------------------------------------------------------------------


@dataclass
class RunLogView:
    """What scoring needs from ``events.jsonl``, read strictly."""

    run_starts: list[RunStartEvent] = field(default_factory=list)
    query_results: dict[Pair, QueryResultEvent] = field(default_factory=dict)
    """Exactly one per (query, seed); the resume key (D7)."""
    parses: dict[Pair, ParseEvent] = field(default_factory=dict)
    """The last ``parse`` of each pair: a pair redone after a crash is parsed again."""
    evals: dict[Pair, EvalEvent] = field(default_factory=dict)
    """The last ``eval`` of each pair."""
    outputs: dict[Pair, LlmCallEvent] = field(default_factory=dict)
    """The last successful planner call of each pair."""
    llm_calls: int = 0
    """Planner calls, retries included, warm-ups excluded."""
    errors: int = 0
    post_check_modes: set[str] = field(default_factory=set)

    @property
    def run_start(self) -> RunStartEvent:
        if not self.run_starts:
            raise RunLogError("the run log has no run_start event")
        return self.run_starts[0]

    @property
    def post_check_mode(self) -> str:
        if len(self.post_check_modes) != 1:
            found = sorted(self.post_check_modes)
            raise RunLogError(f"expected one post-check mode in the run log, found {found}")
        return next(iter(self.post_check_modes))


def load_run_log(events_path: Path) -> RunLogView:
    view = RunLogView()
    for event in read_events(events_path):
        if isinstance(event, RunStartEvent):
            view.run_starts.append(event)
        elif isinstance(event, LlmCallEvent):
            check = (event.model_extra or {}).get("post_check")
            if isinstance(check, dict) and isinstance(check.get("mode"), str):
                view.post_check_modes.add(check["mode"])
            if event.role == WARMUP_ROLE:
                continue
            view.llm_calls += 1
            if event.error is None and event.query_id is not None and event.seed is not None:
                view.outputs[(event.query_id, event.seed)] = event
        elif isinstance(event, ParseEvent):
            view.parses[(event.query_id, event.seed)] = event
        elif isinstance(event, EvalEvent):
            view.evals[(event.query_id, event.seed)] = event
        elif isinstance(event, QueryResultEvent):
            pair = (event.query_id, event.seed)
            if pair in view.query_results:
                raise RunLogError(f"{events_path}: a second query_result for {pair}")
            view.query_results[pair] = event
        elif isinstance(event, ErrorEvent):
            view.errors += 1
    return view


# --- plans files ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanRow:
    """One line of ``plans_seed{n}.jsonl``: the evaluator's input for one query (D7)."""

    idx: int
    """The query's 1-based position in the validation split."""
    query: str
    plan: Plan | None

    @property
    def query_id(self) -> str:
        return query_id_for(self.idx)


def query_index(query_id: str) -> int:
    return int(query_id.removeprefix("val-"))


def plans_for(
    view: RunLogView, seed: int, query_ids: Sequence[str], queries: Mapping[str, str]
) -> list[PlanRow]:
    """The plans of ``seed``, re-parsed from the stored output of each pair's last successful call
    and checked against its ``query_result`` and ``parse`` events. ``queries`` maps a query id to
    its query text (a planner-visible field)."""
    rows = []
    for query_id in query_ids:
        pair = (query_id, seed)
        result = view.query_results.get(pair)
        if result is None:
            raise RunLogError(f"no query_result for {pair}: the run is incomplete")
        call = view.outputs.get(pair)
        plan = None
        if call is not None and call.output_text is not None:
            parsed = parse_plan(call.output_text)
            plan = parsed.plan
            logged = view.parses.get(pair)
            if logged is None or (logged.ok, logged.n_days) != (parsed.ok, parsed.n_days):
                raise RunLogError(f"re-parsing {pair} disagrees with its parse event (R2)")
        if (plan is not None) != (result.status == "delivered"):
            raise RunLogError(f"{pair}: plan and query_result status disagree")
        rows.append(PlanRow(query_index(query_id), queries[query_id], plan))
    return rows


def plans_line(row: PlanRow) -> str:
    return json.dumps({"idx": row.idx, "query": row.query, "plan": row.plan}, ensure_ascii=False)


def write_lines(path: Path, lines: Iterable[str]) -> None:
    """Write text lines, each ending in LF, atomically."""
    write_text(path, "".join(line + "\n" for line in lines))


def write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_plans_file(path: Path, rows: Sequence[PlanRow]) -> None:
    write_lines(path, (plans_line(row) for row in rows))


def read_plans_file(path: Path) -> list[PlanRow]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        rows.append(PlanRow(data["idx"], data["query"], data["plan"]))
    return rows


def dump_json(model: BaseModel) -> str:
    """Whole-file JSON: indented by 2, keys in model order, with a final newline."""
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


# --- per-plan results ----------------------------------------------------------------------------


def evaluate_plan(bridge: EvaluatorBridge, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
    """The evaluator's verdict on one plan, through the bridge. The run and the rescore both call
    this, once per plan."""
    return bridge.per_plan(record, plan)


def result_from_event(event: EvalEvent) -> PerPlanResult:
    return PerPlanResult(
        query_id=event.query_id,
        delivered=event.delivered,
        commonsense=event.commonsense,
        hard=event.hard,
    )


def _group_json(group: ConstraintGroup | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if group is None:
        return None
    return {key: [group[key][0], group[key][1]] for key in keys}


def per_plan_line(result: PerPlanResult) -> str:
    return json.dumps(
        {
            "idx": query_index(result.query_id),
            "query_id": result.query_id,
            "delivered": result.delivered,
            "commonsense": _group_json(result.commonsense, COMMONSENSE_KEYS),
            "hard": _group_json(result.hard, HARD_KEYS),
        },
        ensure_ascii=False,
    )


# --- scores ------------------------------------------------------------------------------------


def is_full(query_ids: Sequence[str]) -> bool:
    """Whether ``query_ids`` are all 180 validation queries, in order."""
    return list(query_ids) == [query_id_for(i) for i in range(1, N_VALIDATION + 1)]


def score_seed(
    results: Sequence[PerPlanResult],
    records: Sequence[EvalRecord],
    *,
    plans_path: Path,
    bridge: EvaluatorBridge,
    full: bool,
) -> tuple[OfficialScores, Source]:
    """The six official scores of one seed (D5 §Wrapper). ``records`` are the scored queries in
    plans-file order."""
    local = aggregate(results, records)
    if not full:
        return local, "subset_aggregate"
    with tempfile.TemporaryDirectory(prefix="tripartite-records-") as tmp:
        records_path = Path(tmp) / "records.jsonl"
        write_bridge_records(records, records_path)
        official = bridge.aggregate(plans_path, records_path)
    differences = {
        key: abs(official.scores[key] - local.scores[key])
        for key in METRIC_KEYS
        if abs(official.scores[key] - local.scores[key]) > AGGREGATE_TOLERANCE
    }
    if differences:
        raise AggregateMismatchError(
            f"aggregate() differs from the official eval_score by more than "
            f"{AGGREGATE_TOLERANCE}: {differences}"
        )
    return official, "official_eval_score"


def _stats(values: Iterable[float | None]) -> Stats:
    present = [float(v) for v in values if v is not None]
    if not present:
        return Stats(mean=None, median=None, p95=None)
    return Stats(
        mean=statistics.fmean(present),
        median=float(statistics.median(present)),
        p95=nearest_rank_p95(present),
    )


def _summary(values: Mapping[int, float]) -> MetricSummary:
    ordered = [values[seed] for seed in values]
    return MetricSummary(
        per_seed={str(seed): value for seed, value in values.items()},
        mean=statistics.fmean(ordered),
        sd=statistics.stdev(ordered) if len(ordered) >= 2 else None,
    )


def build_metrics(
    view: RunLogView,
    *,
    run_id: str,
    kind: RunKind,
    config_hash: str,
    query_ids: Sequence[str],
    seeds: Sequence[int],
    per_seed: Mapping[int, Mapping[OfficialMetric, float]],
    created_at: datetime,
    finished_at: datetime,
) -> Metrics:
    """``metrics.json`` (D7), from the run log and each seed's official scores."""
    pairs = [(query_id, seed) for seed in seeds for query_id in query_ids]
    results = [view.query_results[pair] for pair in pairs]
    reasons = Counter(r.failure_reason or "unknown" for r in results if r.status != "delivered")
    parses = [view.parses[pair] for pair in pairs if pair in view.parses]
    attempted, ok = len(parses), sum(p.ok for p in parses)
    totals = [r.totals for r in results]
    return Metrics(
        schema_version=1,
        run_id=run_id,
        kind=kind,
        config_hash=config_hash,
        created_at=created_at,
        finished_at=finished_at,
        subset=not is_full(query_ids),
        n_queries=len(query_ids),
        seeds=list(seeds),
        post_check_mode=view.post_check_mode,
        metrics={
            key: _summary({seed: per_seed[seed][key] for seed in seeds}) for key in METRIC_KEYS
        },
        non_delivery={
            **dict.fromkeys(NON_DELIVERY_REASONS, 0),
            **dict(sorted(reasons.items())),
        },
        parse=ParseSummary(
            attempted=attempted,
            ok=ok,
            failure_rate=1 - ok / attempted if attempted else None,
        ),
        tokens=TokenStats(
            input=_stats(t.input_tokens for t in totals),
            output=_stats(t.output_tokens for t in totals),
            thinking=_stats(t.thinking_tokens for t in totals),
        ),
        latency_ms=LatencyStats(
            wall=_stats(t.wall_ms for t in totals),
            load=_stats(t.load_ms for t in totals),
            prefill=_stats(t.prefill_ms for t in totals),
            generation=_stats(t.generation_ms for t in totals),
        ),
    )


def score_files(seeds: Iterable[int]) -> list[str]:
    """The files ``write_scores`` writes, in the order it writes them."""
    names = []
    for seed in seeds:
        names += [f"per_plan_eval_seed{seed}.jsonl", f"metrics_seed{seed}.json"]
    return [*names, METRICS_FILE]


def write_scores(
    out_dir: Path,
    *,
    view: RunLogView,
    run_id: str,
    kind: RunKind,
    config_hash: str,
    query_ids: Sequence[str],
    seeds: Sequence[int],
    results_by_seed: Mapping[int, Sequence[PerPlanResult]],
    plans_paths: Mapping[int, Path],
    records: Mapping[str, EvalRecord],
    bridge: EvaluatorBridge,
    created_at: datetime,
    finished_at: datetime,
) -> Metrics:
    """Write every per-seed score file and ``metrics.json`` into ``out_dir``: the one scoring
    code path, shared by the run and by ``rescore`` (R1)."""
    full = is_full(query_ids)
    scored = [records[query_id] for query_id in query_ids]
    per_seed: dict[int, Mapping[OfficialMetric, float]] = {}
    for seed in seeds:
        results = list(results_by_seed[seed])
        if [r.query_id for r in results] != list(query_ids):
            raise RunLogError(f"seed {seed}: the per-plan results do not match the run's queries")
        write_lines(out_dir / f"per_plan_eval_seed{seed}.jsonl", map(per_plan_line, results))
        scores, source = score_seed(
            results, scored, plans_path=plans_paths[seed], bridge=bridge, full=full
        )
        metrics_seed = MetricsSeed(
            schema_version=1,
            run_id=run_id,
            seed=seed,
            subset=not full,
            n_queries=len(query_ids),
            source=source,
            scores=scores.scores,
            detailed=scores.detailed,
        )
        write_text(out_dir / f"metrics_seed{seed}.json", dump_json(metrics_seed))
        per_seed[seed] = scores.scores
    metrics = build_metrics(
        view,
        run_id=run_id,
        kind=kind,
        config_hash=config_hash,
        query_ids=query_ids,
        seeds=seeds,
        per_seed=per_seed,
        created_at=created_at,
        finished_at=finished_at,
    )
    write_text(out_dir / METRICS_FILE, dump_json(metrics))
    return metrics


def format_metrics(metrics: Metrics) -> list[str]:
    """The CLI's report: the six scores as percentages (stored files keep rates, D7)."""
    lines = []
    for key, summary in metrics.metrics.items():
        per_seed = ", ".join(f"seed {s}: {100 * v:.1f}%" for s, v in summary.per_seed.items())
        sd = "" if summary.sd is None else f" ± {100 * summary.sd:.1f}"
        lines.append(f"{key}: {100 * summary.mean:.1f}%{sd} ({per_seed})")
    lines.append(
        f"parse: {metrics.parse.ok}/{metrics.parse.attempted} ok; not delivered: "
        + ", ".join(f"{k} {v}" for k, v in metrics.non_delivery.items())
    )
    return lines
