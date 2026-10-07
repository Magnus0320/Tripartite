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

A succeeded run is read with the strict reader (D7). Any other run may end in a half-written
line: one in progress is being appended to, and a failed or interrupted one may have been cut
off by a crash. That one line is skipped, and never repaired; resume alone repairs.
"""

import csv
from pathlib import Path
from typing import Final

from tripartite.api.schemas import (
    BatchSummary,
    Constraint,
    DayPlan,
    ItemDetail,
    MetricSummary,
    ModelRef,
    Progress,
    RunDetail,
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
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import (
    EvalEvent,
    LlmCallEvent,
    Metrics,
    ParseEvent,
    QueryResultEvent,
    RunManifest,
    validate_run_id,
)

ACTIVE: Final = ("queued", "running")
"""The statuses of a run that is not finished (D7)."""
DATA_ERRORS: Final = (DataError, OSError, ValueError, csv.Error, KeyError)
"""What the ``PlannerInput`` loader raises when the data, or the run's query in it, is missing."""


class RunNotFoundError(LookupError):
    """No run with this id: the id is malformed, or ``runs/<run_id>/manifest.json`` is absent."""


class QueryUnavailableError(RuntimeError):
    """The text of a run's query cannot be read: the data is missing or invalid."""


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
    """``RunDetail.error``: ``"<type>: <message>"``, or None."""
    if manifest.error is None:
        return None
    return f"{manifest.error.type}: {manifest.error.message}"


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
        raise QueryUnavailableError(str(message)) from None


def _total_ms(calls: list[LlmCallEvent]) -> float | None:
    reported = [
        call.timing_ms.total_reported for call in calls if call.timing_ms.total_reported is not None
    ]
    return sum(reported) if reported else None


def _item(run_dir: Path, manifest: RunManifest) -> ItemDetail | None:
    """The one pair of a single run, or None until it has its ``query_result``."""
    query_id, seed = manifest.run_start.query_ids[0], manifest.run_start.seeds[0]
    pair = (query_id, seed)
    view = RunLogView()
    calls: list[LlmCallEvent] = []
    evaluated: EvalEvent | None = None
    events = read_events(
        run_dir / EVENTS_FILE, tolerate_partial_tail=manifest.status != "succeeded"
    )
    for event in events:
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
        item=_item(run_dir, manifest) if single else None,
        summary=None if single else _summary(run_dir, manifest),
    )


def load_run_detail(runs_dir: Path, run_id: str) -> RunDetail:
    """``RunDetail`` of ``runs_dir/<run_id>``; ``RunNotFoundError`` if there is no such run."""
    run_dir = find_run_dir(runs_dir, run_id)
    return run_detail(run_dir, read_manifest(run_dir))
