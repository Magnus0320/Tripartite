"""D2 golden test 7(a): the upstream example plans survive rendering and parsing.

Each delivered plan in the vendored ``postprocess/example_evaluation.jsonl`` is rendered into the
official text format (the layout of the prompt's own example) and parsed back.

The upstream plans are not uniform, and the official text format can carry only an integer day
number and the seven fields. The expected dict is therefore the projection of each upstream day
that the format can express (Architecture question AQ2 in the M4 PR):

- ``days`` is the upstream ``days`` or ``day`` key (123 plans use ``day``);
- the seven fields keep their upstream values; a field the upstream day lacks is not rendered,
  so it parses as ``-`` with a ``missing_field`` warning;
- upstream keys outside the format (``cost``, ``total_estimated_costs``, ``remaining_budget``)
  are not rendered, and the two upstream dicts with no integer day number (a ``"Summary"`` day
  and a costs-only dict) are left out.

The counts are pinned below, so the fixture cannot drift unnoticed. The evaluator never reads the
day-number key: it pairs days by position.
"""

import json
from collections import Counter
from typing import Any

from tripartite.config import REPO_ROOT
from tripartite.parse.text_plan_parser import FIELDS, parse_plan

EXAMPLE = REPO_ROOT / "vendor" / "travelplanner" / "postprocess" / "example_evaluation.jsonl"
LABELS = {
    "current_city": "Current City",
    "transportation": "Transportation",
    "breakfast": "Breakfast",
    "attraction": "Attraction",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "accommodation": "Accommodation",
}


def delivered_plans() -> list[tuple[int, list[dict[str, Any]]]]:
    rows = [json.loads(line) for line in EXAMPLE.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 180
    return [(row["idx"], row["plan"]) for row in rows if row["plan"]]


def day_number(unit: dict[str, Any]) -> int | None:
    number = unit.get("days", unit.get("day"))
    return number if type(number) is int else None


def render(plan: list[dict[str, Any]]) -> str:
    """The official text format, as in the prompt's example: a header, then one line per field."""
    blocks = []
    for unit in plan:
        number = day_number(unit)
        if number is None:
            continue
        lines = [f"Day {number}:"] + [f"{LABELS[f]}: {unit[f]}" for f in FIELDS if f in unit]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def expected(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"days": number, **{f: unit.get(f, "-") for f in FIELDS}}
        for unit in plan
        if (number := day_number(unit)) is not None
    ]


def test_every_delivered_example_plan_round_trips() -> None:
    plans = delivered_plans()
    missing: Counter[str] = Counter()

    for idx, plan in plans:
        result = parse_plan(render(plan))
        assert result.plan == expected(plan), f"example plan idx {idx}"
        assert result.failure_reason is None
        for warning in result.warnings:
            assert warning.startswith("missing_field:"), (idx, warning)
            missing[warning] += 1

    assert missing == Counter({"missing_field:attraction": 3})


def test_the_example_file_is_the_one_the_projection_was_written_for() -> None:
    """Pins the shape of the upstream file, so that any drift in it fails here, loudly."""
    plans = delivered_plans()
    units = [unit for _, plan in plans for unit in plan]
    excluded = [(idx, unit) for idx, plan in plans for unit in plan if day_number(unit) is None]

    assert len(plans) == 161
    assert sum(all("day" in u for u in plan) for _, plan in plans) == 123
    assert len(units) == 793
    assert [(idx, sorted(unit)) for idx, unit in excluded] == [
        (94, ["accommodation", "attraction", "breakfast", "current_city", "day", "dinner", "lunch",
              "remaining_budget", "total_estimated_costs", "transportation"]),
        (163, ["total_estimated_costs"]),
    ]  # fmt: skip
    extra = Counter(k for u in units if day_number(u) is not None for k in u if k not in FIELDS)
    assert extra == Counter({"day": 608, "days": 183, "cost": 2})  # 791 rendered days
    # Every rendered value is already what the parser's value rule would produce, so the
    # round trip compares the upstream values themselves.
    for unit in units:
        if day_number(unit) is None:
            continue
        for f in FIELDS:
            if f in unit:
                value = unit[f]
                assert isinstance(value, str)
                assert value == value.strip() != ""
                assert "$" not in value
                assert "\n" not in value
