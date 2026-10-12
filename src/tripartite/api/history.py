"""A run directory as the API serves it (ARCHITECTURE.md D7, D8).

``load_run_detail`` maps ``runs/<run_id>/`` to D8's ``RunDetail`` and invents nothing:

- ``manifest.json`` gives the status, the stage, the times, the error and the ``run_start`` pins.
- A **single** run's ``item`` comes from ``events.jsonl``, once its one pair has a
  ``query_result``: the pair's last ``eval`` event (the verdict and the 13 constraint rows), its
  planner ``llm_call`` events (``raw_output``, ``total_ms``) and the ``query_result`` totals. The
  plan is re-parsed from the stored output by ``pipeline.metrics.plans_for``, exactly as the
  run's own plans file is written (R2). The query text is the ``PlannerInput`` field (D3).
- A **batch** run's ``summary`` is the manifest's progress plus ``metrics.json``'s six official
  metrics, which are empty until the run is scored.

F3 reads the same files. ``list_runs`` is the history: the directories of ``runs/`` whose name is
a run id and that hold a readable ``manifest.json``, newest first by run id (an id starts with
its UTC timestamp), one page at a time. Anything else in ``runs/``, such as ``runs/reproduce/``,
is skipped without error. ``list_items`` gives a batch run's finished pairs of one seed, and
``load_item_detail`` one pair of any run, built by the function that builds ``RunDetail.item``.

A succeeded run is read with the strict reader (D7). Any other run may end in a half-written
line: one in progress is being appended to, and a failed or interrupted one may have been cut
off by a crash. That one line is skipped, and never repaired; resume alone repairs.

One unreadable run never breaks the history list: a single run whose log is corrupt, or a batch
run whose ``metrics.json`` is invalid, is listed with those fields null, and the error is logged.
That run's own routes still answer 500.
"""

import csv
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from tripartite.api.messages import public_message
from tripartite.api.schemas import (
    BatchSummary,
    Constraint,
    DayPlan,
    ItemDetail,
    ItemList,
    ItemSummary,
    MetricSummary,
    ModelRef,
    Progress,
    RunDetail,
    RunHeadline,
    RunList,
    RunSummary,
    Usage,
)
from tripartite.data.manifest import DataError
from tripartite.data.planner_inputs import get_planner_input
from tripartite.evaluation.bridge_client import Plan
from tripartite.evaluation.constraints import constraint_rows
from tripartite.parse.text_plan_parser import EMPTY_VALUE
from tripartite.pipeline.metrics import METRICS_FILE, RunLogView, plans_for, result_from_event
from tripartite.pipeline.run import EVENTS_FILE, MANIFEST_FILE, read_manifest
from tripartite.planner.sole_planner import WARMUP_ROLE
from tripartite.runlog.reader import RunLogError, read_events
from tripartite.runlog.schema import (
    EvalEvent,
    Event,
    LlmCallEvent,
    Metrics,
    ParseEvent,
    QueryResultEvent,
    RunManifest,
    validate_run_id,
)

logger: Final = logging.getLogger("tripartite.api")

ACTIVE: Final = ("queued", "running")
"""The statuses of a run that is not finished (D7)."""
DATA_ERRORS: Final = (DataError, OSError, ValueError, csv.Error, KeyError)
"""What the ``PlannerInput`` loader raises when the data, or the run's query in it, is missing."""


class RunNotFoundError(LookupError):
    """No run with this id: the id is malformed, or ``runs/<run_id>/manifest.json`` is absent."""


class QueryUnavailableError(RuntimeError):
    """The text of a run's query cannot be read: the data is missing or invalid."""


class NoItemsError(LookupError):
    """The run has no such item list: it is a single run, or it does not have the seed."""


class ItemNotFoundError(LookupError):
    """The run has no such (query, seed) pair, or the pair has no result yet."""


def find_run_dir(runs_dir: Path, run_id: str) -> Path:
    """``runs_dir/<run_id>``, for a well-formed id (so no path leaves ``runs_dir``) whose
    directory has a manifest. Folders without one, such as ``runs/reproduce/``, are not runs."""
    try:
        run_dir = runs_dir / validate_run_id(run_id)
    except ValueError:
        raise RunNotFoundError(f"unknown run_id {run_id!r}") from None
    if not (run_dir / MANIFEST_FILE).is_file():
        raise RunNotFoundError(f"unknown run_id {run_id!r}")
    return run_dir


def error_text(manifest: RunManifest) -> str | None:
    """``RunDetail.error``: ``"<type>: <message>"`` without absolute paths, or None. The
    manifest keeps the full text, so it is not logged again on every read."""
    if manifest.error is None:
        return None
    return public_message(f"{manifest.error.type}: {manifest.error.message}", log=False)


def attractions(attraction: str) -> list[str]:
    """``attraction`` split on ``;``, trimmed, without empty strings and ``-`` (D8)."""
    parts = (part.strip() for part in attraction.split(";"))
    return [part for part in parts if part and part != EMPTY_VALUE]


def day_plans(plan: Plan) -> list[DayPlan]:
    return [
        DayPlan(
            day=int(day["days"]),
            current_city=str(day["current_city"]),
            transportation=str(day["transportation"]),
            breakfast=str(day["breakfast"]),
            attraction=str(day["attraction"]),
            attractions=attractions(str(day["attraction"])),
            lunch=str(day["lunch"]),
            dinner=str(day["dinner"]),
            accommodation=str(day["accommodation"]),
        )
        for day in plan
    ]


def _query_text(query_id: str) -> str:
    try:
        return get_planner_input(query_id).query
    except DATA_ERRORS as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        raise QueryUnavailableError(public_message(str(message))) from None


def _total_ms(calls: list[LlmCallEvent]) -> float | None:
    reported = [
        call.timing_ms.total_reported for call in calls if call.timing_ms.total_reported is not None
    ]
    return sum(reported) if reported else None


def _events(run_dir: Path, manifest: RunManifest) -> Iterator[Event]:
    """The run's events, by D7's reader rule for the API: strict for a succeeded run, and
    skipping a half-written last line for any other."""
    return read_events(run_dir / EVENTS_FILE, tolerate_partial_tail=manifest.status != "succeeded")


def load_item(run_dir: Path, manifest: RunManifest, query_id: str, seed: int) -> ItemDetail | None:
    """One (query, seed) pair of a run, or None until it has its ``query_result``."""
    pair = (query_id, seed)
    view = RunLogView()
    calls: list[LlmCallEvent] = []
    evaluated: EvalEvent | None = None
    for event in _events(run_dir, manifest):
        if isinstance(event, LlmCallEvent):
            if event.role != WARMUP_ROLE and (event.query_id, event.seed) == pair:
                calls.append(event)
                if event.error is None:
                    view.outputs[pair] = event
        elif isinstance(event, ParseEvent):
            view.parses[(event.query_id, event.seed)] = event
        elif isinstance(event, EvalEvent):
            if (event.query_id, event.seed) == pair:
                evaluated = event
        elif isinstance(event, QueryResultEvent):
            view.query_results[(event.query_id, event.seed)] = event
    result = view.query_results.get(pair)
    if result is None or evaluated is None:
        return None

    query = _query_text(query_id)
    plan = plans_for(view, seed, [query_id], {query_id: query})[0].plan
    output = view.outputs.get(pair)
    totals = result.totals
    return ItemDetail(
        query_id=query_id,
        seed=seed,
        query=query,
        delivered=evaluated.delivered,
        failure_reason=result.failure_reason,
        plan=None if plan is None else day_plans(plan),
        constraints=[
            Constraint(
                key=row.key,
                label=row.label,
                group=row.group,
                status=row.status,
                message=row.message,
            )
            for row in constraint_rows(result_from_event(evaluated))
        ],
        commonsense_pass=evaluated.commonsense_pass,
        hard_pass=evaluated.hard_pass,
        final_pass=evaluated.final_pass,
        usage=Usage(
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            thinking_tokens=totals.thinking_tokens,
            load_ms=totals.load_ms,
            prefill_ms=totals.prefill_ms,
            generation_ms=totals.generation_ms,
            total_ms=_total_ms(calls),
            wall_ms=totals.wall_ms,
        ),
        raw_output=(output.output_text or "") if output is not None else "",
    )


def _summary(run_dir: Path, manifest: RunManifest) -> BatchSummary:
    metrics: dict[str, MetricSummary] = {}
    path = run_dir / METRICS_FILE
    if path.is_file():
        scored = Metrics.model_validate_json(path.read_bytes())
        metrics = {
            key: MetricSummary(per_seed=dict(value.per_seed), mean=value.mean, sd=value.sd)
            for key, value in scored.metrics.items()
        }
    progress = Progress(done=manifest.progress.done, total=manifest.progress.total)
    return BatchSummary(progress=progress, metrics=metrics)


def run_detail(run_dir: Path, manifest: RunManifest) -> RunDetail:
    start = manifest.run_start
    single = start.kind == "single"
    return RunDetail(
        run_id=run_dir.name,
        kind=start.kind,
        status=manifest.status,
        stage=manifest.stage,
        created_at=manifest.created_at,
        finished_at=manifest.finished_at,
        config_hash=start.config_hash,
        model=ModelRef(tag=start.model.tag, digest=start.model.digest),
        prompt_version=start.prompt_version,
        error=error_text(manifest),
        item=load_item(run_dir, manifest, start.query_ids[0], start.seeds[0]) if single else None,
        summary=None if single else _summary(run_dir, manifest),
    )


def load_run_detail(runs_dir: Path, run_id: str) -> RunDetail:
    """``RunDetail`` of ``runs_dir/<run_id>``; ``RunNotFoundError`` if there is no such run."""
    run_dir = find_run_dir(runs_dir, run_id)
    return run_detail(run_dir, read_manifest(run_dir))


# --- history (F3) --------------------------------------------------------------------------------


def _verdicts(run_dir: Path, manifest: RunManifest) -> dict[tuple[str, int], EvalEvent]:
    """The last ``eval`` of every pair that has its ``query_result``, so that a pair counts as
    finished here exactly when ``load_item`` returns it."""
    evals: dict[tuple[str, int], EvalEvent] = {}
    finished: set[tuple[str, int]] = set()
    for event in _events(run_dir, manifest):
        if isinstance(event, EvalEvent):
            evals[(event.query_id, event.seed)] = event
        elif isinstance(event, QueryResultEvent):
            finished.add((event.query_id, event.seed))
    return {pair: event for pair, event in evals.items() if pair in finished}


def _headline(run_dir: Path) -> RunHeadline | None:
    path = run_dir / METRICS_FILE
    if not path.is_file():
        return None
    metrics = Metrics.model_validate_json(path.read_bytes()).metrics
    return RunHeadline(
        final_pass_rate_mean=metrics["Final Pass Rate"].mean,
        delivery_rate_mean=metrics["Delivery Rate"].mean,
    )


def run_summary(run_dir: Path, manifest: RunManifest) -> RunSummary:
    """One row of the history. What cannot be read is null and logged; it never raises for a
    corrupt log or an invalid ``metrics.json``."""
    start = manifest.run_start
    single = start.kind == "single"
    verdict: EvalEvent | None = None
    headline: RunHeadline | None = None
    try:
        if single:
            verdict = _verdicts(run_dir, manifest).get((start.query_ids[0], start.seeds[0]))
        else:
            headline = _headline(run_dir)
    except (RunLogError, OSError, ValueError, KeyError) as exc:
        logger.warning("run %s is listed without its result: %s", run_dir.name, exc)
    return RunSummary(
        run_id=run_dir.name,
        kind=start.kind,
        status=manifest.status,
        created_at=manifest.created_at,
        query_id=start.query_ids[0] if single else None,
        seed=start.seeds[0] if single else None,
        final_pass=None if verdict is None else verdict.final_pass,
        delivered=None if verdict is None else verdict.delivered,
        headline=headline,
    )


def _is_run_id(name: str) -> bool:
    try:
        validate_run_id(name)
    except ValueError:
        return False
    return True


def list_runs(runs_dir: Path, limit: int, before: str | None = None) -> RunList:
    """At most ``limit`` runs, newest first, all of them older than ``before`` (a run id, which
    need not exist). Only the manifests of the page are read; a directory without a readable
    manifest is not a run and is skipped."""
    if not runs_dir.is_dir():
        return RunList(items=[], next_before=None)
    run_ids = sorted(
        (
            path.parent.name
            for path in runs_dir.glob(f"*/{MANIFEST_FILE}")
            if _is_run_id(path.parent.name)
        ),
        reverse=True,
    )
    items: list[RunSummary] = []
    for run_id in run_ids:
        if before is not None and run_id >= before:
            continue
        try:
            manifest = read_manifest(runs_dir / run_id)
        except (OSError, ValueError):
            continue
        if len(items) == limit:
            return RunList(items=items, next_before=items[-1].run_id)
        items.append(run_summary(runs_dir / run_id, manifest))
    return RunList(items=items, next_before=None)


def list_items(runs_dir: Path, run_id: str, seed: int) -> ItemList:
    """The finished pairs of ``seed`` in a batch run, in the run's query order."""
    run_dir = find_run_dir(runs_dir, run_id)
    manifest = read_manifest(run_dir)
    start = manifest.run_start
    if start.kind != "batch":
        raise NoItemsError(f"run {run_id} is a single run and has no item list")
    if seed not in start.seeds:
        raise NoItemsError(f"run {run_id} has no seed {seed}")
    verdicts = _verdicts(run_dir, manifest)
    return ItemList(
        items=[
            ItemSummary(
                query_id=query_id,
                seed=seed,
                delivered=verdict.delivered,
                final_pass=verdict.final_pass,
                commonsense_pass=verdict.commonsense_pass,
                hard_pass=verdict.hard_pass,
            )
            for query_id in start.query_ids
            if (verdict := verdicts.get((query_id, seed))) is not None
        ]
    )


def load_item_detail(runs_dir: Path, run_id: str, query_id: str, seed: int) -> ItemDetail:
    """One pair of a run of either kind, as ``RunDetail.item`` is built for a single run."""
    run_dir = find_run_dir(runs_dir, run_id)
    manifest = read_manifest(run_dir)
    start = manifest.run_start
    if query_id not in start.query_ids or seed not in start.seeds:
        raise ItemNotFoundError(f"run {run_id} has no item ({query_id!r}, {seed})")
    item = load_item(run_dir, manifest, query_id, seed)
    if item is None:
        raise ItemNotFoundError(f"item ({query_id!r}, {seed}) of run {run_id} has no result yet")
    return item
