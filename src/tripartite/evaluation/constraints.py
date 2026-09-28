"""Per-plan evaluator results and their UI rows (ARCHITECTURE.md D5 §Wrapper, D8 ``Constraint``).

``PerPlanResult`` is what the bridge returns for one plan: ``delivered``, and the commonsense
and hard groups as ``{key: (value, message)}``, where ``value`` is ``True``, ``False`` or
``None`` (not applicable; A-014). A group is ``None`` when it was not evaluated: both groups
for an undelivered plan, and the hard group when ``eval.py``'s gating skipped it.

``constraint_rows`` turns a result into the UI list: always 8 commonsense rows then 5 hard
rows, in ``eval.py``'s ``key_dict`` order, each labelled with the paper's name from
``eval.py::paper_term_mapping``. ``status`` is ``pass`` (true), ``fail`` (false),
``not_applicable`` (null) or ``not_evaluated`` (the group is null).
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from tripartite.runlog.schema import ConstraintResult

COMMONSENSE_KEYS: Final = (
    "is_valid_information_in_current_city",
    "is_valid_information_in_sandbox",
    "is_reasonable_visiting_city",
    "is_valid_restaurants",
    "is_valid_transportation",
    "is_valid_attractions",
    "is_valid_accommodation",
    "is_not_absent",
)
"""The 8 commonsense checks, in ``eval.py``'s ``key_dict['commonsense']`` order."""
HARD_KEYS: Final = (
    "valid_cost",
    "valid_room_rule",
    "valid_cuisine",
    "valid_room_type",
    "valid_transportation",
)
"""The 5 hard checks, in ``eval.py``'s ``key_dict['hard']`` order."""
LABELS: Final = MappingProxyType(
    {
        "is_valid_information_in_current_city": "Within Current City",
        "is_valid_information_in_sandbox": "Within Sandbox",
        "is_reasonable_visiting_city": "Reasonable City Route",
        "is_valid_restaurants": "Diverse Restaurants",
        "is_valid_transportation": "Non-conf. Transportation",
        "is_valid_attractions": "Diverse Attractions",
        "is_valid_accommodation": "Minimum Nights Stay",
        "is_not_absent": "Complete Information",
        "valid_cost": "Budget",
        "valid_room_rule": "Room Rule",
        "valid_cuisine": "Cuisine",
        "valid_room_type": "Room Type",
        "valid_transportation": "Transportation",
    }
)
"""``eval.py::paper_term_mapping``'s ``mapping_dict``, verbatim."""

Group = Literal["commonsense", "hard"]
Status = Literal["pass", "fail", "not_applicable", "not_evaluated"]
ConstraintGroup = dict[str, ConstraintResult]


@dataclass(frozen=True, slots=True)
class PerPlanResult:
    """The evaluator's verdict on one plan (the bridge's ``per_plan`` response)."""

    query_id: str
    delivered: bool
    commonsense: ConstraintGroup | None
    hard: ConstraintGroup | None


@dataclass(frozen=True, slots=True)
class ConstraintRow:
    key: str
    label: str
    group: Group
    status: Status
    message: str | None


def _status(value: bool | None) -> Status:
    if value is None:
        return "not_applicable"
    return "pass" if value else "fail"


def _rows(
    group: Group, keys: tuple[str, ...], results: ConstraintGroup | None
) -> list[ConstraintRow]:
    rows = []
    for key in keys:
        if results is None:
            status: Status = "not_evaluated"
            message = None
        else:
            value, message = results[key]
            status = _status(value)
        rows.append(ConstraintRow(key, LABELS[key], group, status, message))
    return rows


def constraint_rows(result: PerPlanResult) -> list[ConstraintRow]:
    """The 8 commonsense rows then the 5 hard rows of ``result``, for the UI (D5, D8)."""
    return [
        *_rows("commonsense", COMMONSENSE_KEYS, result.commonsense),
        *_rows("hard", HARD_KEYS, result.hard),
    ]
