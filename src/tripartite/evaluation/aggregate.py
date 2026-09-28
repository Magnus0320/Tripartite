"""The official metrics over any subset of queries (ARCHITECTURE.md D5 §Wrapper).

``aggregate(results, records)`` reimplements ``eval.py::eval_score`` at e52c87f4 for the
per-plan results of ``n`` queries, with the denominators computed from those ``n`` queries:

- Delivery Rate, Commonsense Macro, Hard Macro and Final Pass Rate: counts over ``n``.
- Commonsense Micro: passing checks over ``8 n``.
- Hard Micro: passing checks over the applicable hard checks, by ``eval.py``'s rules: every
  query has ``valid_cost``; a ``medium`` query adds one for each non-null ``house rule``,
  ``cuisine`` and ``room type`` constraint, and a ``hard`` query one for each of those and
  ``transportation`` (``mapping_constraint_record``). Over the 180 validation queries these
  are 1440 and 420, ``eval.py``'s constants. As in ``eval.py``, every passing hard check counts
  in the numerator, even one the denominator does not count.

The macro counts follow ``eval.py``'s final loop exactly (``plan_pass``). ``detailed`` is
``eval_score``'s second value for the same results, in the JSON form the bridge returns (day
keys as strings), including the ``total`` fields ``eval.py`` adds as a side effect.

Full 180-query runs use the bridge's own ``aggregate`` op; the pipeline asserts the two agree
to 1e-12. The golden test asserts they are equal on the upstream example submission.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol

from tripartite.evaluation.constraints import COMMONSENSE_KEYS, HARD_KEYS, LABELS, PerPlanResult
from tripartite.runlog.schema import OfficialMetric

LEVELS: Final = ("easy", "medium", "hard")
DAYS: Final = (3, 5, 7)
LOCAL_CONSTRAINTS: Final = MappingProxyType(
    {
        "house rule": "valid_room_rule",
        "cuisine": "valid_cuisine",
        "room type": "valid_room_type",
        "transportation": "valid_transportation",
    }
)
"""``eval.py``'s ``constraint_mapping``: local-constraint key -> hard check."""
COUNTED_BY_LEVEL: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "medium": ("valid_room_rule", "valid_cuisine", "valid_room_type"),
        "hard": ("valid_room_rule", "valid_cuisine", "valid_room_type", "valid_transportation"),
    }
)
"""The hard checks whose denominator comes from the query's local constraints, by level."""


class ScoredQuery(Protocol):
    """What ``aggregate`` reads from a query. ``EvalRecord`` has it."""

    @property
    def query_id(self) -> str: ...
    @property
    def level(self) -> str: ...
    @property
    def days(self) -> int: ...
    @property
    def local_constraint(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class Metrics:
    """The six official scores (rates in [0, 1]) and ``eval_score``'s detailed breakdown."""

    scores: dict[OfficialMetric, float]
    detailed: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlanPass:
    commonsense: bool
    hard: bool
    final: bool


def plan_pass(result: PerPlanResult) -> PlanPass:
    """Whether one plan counts toward the macro and final rates, exactly as ``eval.py`` counts.

    A check fails only on ``False``; ``None`` (not applicable) never fails. A plan whose hard
    group was not evaluated counts for neither group, because ``eval.py`` skips it
    (``continue``) before counting.
    """
    if not result.commonsense or result.hard is None:
        return PlanPass(commonsense=False, hard=False, final=False)
    commonsense = not any(v is not None and not v for v, _ in result.commonsense.values())
    hard = not any(v is not None and v is False for v, _ in result.hard.values())
    return PlanPass(commonsense=commonsense, hard=hard, final=commonsense and hard)


Tally = dict[str, dict[str, int]]
"""Check -> {"true": n, "false": n} (and "total" where ``eval.py`` adds it)."""


def _tallies() -> dict[str, dict[int, Tally]]:
    return {level: {day: {} for day in DAYS} for level in LEVELS}


def _count(tallies: Tally, group: Mapping[str, tuple[bool | None, str | None]]) -> None:
    """``eval.py::statistics`` for one plan: ``[value, message].count(True)`` and ``(False)``."""
    for key, pair in group.items():
        entry = tallies.setdefault(key, {"true": 0, "false": 0})
        entry["true"] += list(pair).count(True)
        entry["false"] += list(pair).count(False)


def _cell(query: ScoredQuery) -> tuple[str, int]:
    if query.level not in LEVELS or query.days not in DAYS:
        raise ValueError(f"{query.query_id}: unexpected (level, days) {(query.level, query.days)}")
    return query.level, query.days


def aggregate(results: Sequence[PerPlanResult], records: Sequence[ScoredQuery]) -> Metrics:
    """The official metrics of ``results``, one per query of ``records``, in the same order."""
    n = len(records)
    if n == 0 or len(results) != n:
        raise ValueError(f"need one result per query, got {len(results)} for {n} queries")
    for result, record in zip(results, records, strict=True):
        if result.query_id != record.query_id:
            raise ValueError(f"result {result.query_id} is not for query {record.query_id}")

    commonsense_stats, hard_stats = _tallies(), _tallies()
    count_record = {level: dict.fromkeys(DAYS, 0) for level in LEVELS}
    mapping_record = {
        level: {day: dict.fromkeys(LOCAL_CONSTRAINTS.values(), 0) for day in DAYS}
        for level in COUNTED_BY_LEVEL
    }
    applicable_hard = 0
    for result, record in zip(results, records, strict=True):
        level, day = _cell(record)
        if result.commonsense:
            _count(commonsense_stats[level][day], result.commonsense)
        if result.hard:
            _count(hard_stats[level][day], result.hard)
        count_record[level][day] += 1
        applicable_hard += 1  # valid_cost
        for key, check in LOCAL_CONSTRAINTS.items():
            if record.local_constraint[key] is not None:
                if level not in mapping_record:
                    # eval.py raises KeyError here: easy queries never carry local constraints.
                    raise ValueError(f"{record.query_id}: an easy query with a {key!r} constraint")
                mapping_record[level][day][check] += 1
                applicable_hard += check in COUNTED_BY_LEVEL[level]

    passes = {"commonsense": 0, "hard": 0}
    for group, stats, keys in (
        ("commonsense", commonsense_stats, COMMONSENSE_KEYS),
        ("hard", hard_stats, HARD_KEYS),
    ):
        for level in LEVELS:
            for day in DAYS:
                for key in keys:
                    entry = stats[level][day].get(key)
                    if entry is None:
                        continue
                    passes[group] += entry["true"]
                    if group == "commonsense" or key == "valid_cost":
                        entry["total"] = count_record[level][day]
                    elif key in COUNTED_BY_LEVEL.get(level, ()):
                        entry["total"] = mapping_record[level][day][key]

    macro = [plan_pass(result) for result in results]
    scores: dict[OfficialMetric, float] = {
        "Delivery Rate": sum(r.delivered for r in results) / n,
        "Commonsense Constraint Micro Pass Rate": passes["commonsense"] / (8 * n),
        "Commonsense Constraint Macro Pass Rate": sum(p.commonsense for p in macro) / n,
        "Hard Constraint Micro Pass Rate": passes["hard"] / applicable_hard,
        "Hard Constraint Macro Pass Rate": sum(p.hard for p in macro) / n,
        "Final Pass Rate": sum(p.final for p in macro) / n,
    }
    detailed = {
        "Commonsense Constraint": _paper_terms(commonsense_stats),
        "Hard Constraint": _paper_terms(hard_stats),
    }
    return Metrics(scores=scores, detailed=detailed)


def _paper_terms(stats: dict[str, dict[int, Tally]]) -> dict[str, Any]:
    """``eval.py::paper_term_mapping`` in JSON form: day keys as strings, paper names."""
    return {
        level: {str(day): {LABELS[k]: v for k, v in stats[level][day].items()} for day in DAYS}
        for level in LEVELS
    }
