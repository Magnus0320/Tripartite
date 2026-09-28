"""Loaders for ``tests/fixtures/eval_golden/`` (ARCHITECTURE.md D5 §Wrapper, golden test).

The fixtures were generated once, locally, by ``tests.evaluation.generate_eval_golden`` with the
real bridge on the upstream example submission. ``queries.jsonl`` carries only what
``aggregate`` reads from a query (level, days, and which local constraints are set), so the CI
test needs no dataset.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tripartite.evaluation.bridge_client import parse_per_plan
from tripartite.evaluation.constraints import PerPlanResult

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "eval_golden"
LOCAL_CONSTRAINT_KEYS = ("house rule", "cuisine", "room type", "transportation")


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    """The fields ``aggregate`` reads. A set constraint holds a placeholder, never its value."""

    query_id: str
    level: str
    days: int
    local_constraint: dict[str, str | None]


def _lines(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (GOLDEN / name).read_text(encoding="utf-8").splitlines()]


def per_plan_results() -> list[PerPlanResult]:
    """The 180 golden results, each parsed and shape-checked like a live bridge response."""
    return [parse_per_plan(obj["query_id"], obj) for obj in _lines("per_plan.jsonl")]


def queries() -> list[GoldenQuery]:
    return [
        GoldenQuery(
            query_id=obj["query_id"],
            level=obj["level"],
            days=obj["days"],
            local_constraint={
                key: ("<set>" if key in obj["constrained"] else None)
                for key in LOCAL_CONSTRAINT_KEYS
            },
        )
        for obj in _lines("queries.jsonl")
    ]


def official() -> dict[str, Any]:
    """``{"scores", "detailed"}`` from the bridge's ``aggregate`` op (``eval.eval_score``)."""
    result: dict[str, Any] = json.loads((GOLDEN / "official.json").read_text(encoding="utf-8"))
    return result
