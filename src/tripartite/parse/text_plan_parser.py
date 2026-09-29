"""The rule parser ``rule-text`` ``v1`` (ARCHITECTURE.md D2).

The planner writes free text in the official line format, and this parser turns it into the
evaluator's plan: a list of day dicts with the keys ``days, current_city, transportation,
breakfast, attraction, lunch, dinner, accommodation`` (F6). It reads the visible output text only,
never the query or any evaluator field, uses no LLM, and is deterministic, so re-parsing stored
raw outputs gives identical plans (R2).

The rules, in order (D2 §Parser specification):

1. Normalize: CRLF becomes LF. Every ``<think>…</think>`` block is removed; its content becomes
   ``thinking_text``, with the warning ``think_block_in_output``. An unclosed ``<think>`` is left
   as text. Markdown code-fence lines (```` ``` ````), every ``**``, and leading ``#``, ``-``,
   ``*`` or ``•`` markers at line start are removed.
2. A day header is a line matching ``(?i)^\\s*day\\s*(\\d+)\\s*:?\\s*$``. Text before the first
   header is ignored.
3. A field line inside a day matches ``(?i)^\\s*(current city|transportation|breakfast|
   attractions?|lunch|dinner|accommodations?)\\s*:\\s*(.*)$``. Any other non-empty line is
   appended, space-joined, to the previous field of the same day; a line with no previous field
   in its day is dropped. If a label repeats within a day, the first occurrence wins (warning
   ``duplicate_field``), and lines continuing the ignored repeat are dropped with it.
4. Values: every ``$`` is deleted, then whitespace is stripped, and an empty value becomes ``-``.
   A missing field becomes ``-`` (warning ``missing_field:<name>``). Nothing else is rewritten;
   vague entries such as "eat at home" stay as written.
5. Days keep their header numbers, in order of appearance. Numbering other than 1, 2, … n is
   kept and warned once (``day_sequence``).
6. The plan is ``None`` when the text is empty after normalization (``empty_output``), has no day
   header (``no_day_blocks``), or has no field line in any day (``no_fields``). The parser never
   pads or truncates days to match a query: the evaluator judges completeness.
"""

import re
from dataclasses import dataclass, field
from typing import Final, Literal

PARSER_ID: Final = "rule-text"
PARSER_VERSION: Final = "v1"
PARSER_VERSION_ID: Final = f"{PARSER_ID}/{PARSER_VERSION}"
"""What ``parse`` events and ``run_start.parser_version`` record (§6)."""

FIELDS: Final = (
    "current_city",
    "transportation",
    "breakfast",
    "attraction",
    "lunch",
    "dinner",
    "accommodation",
)
"""The seven fields of a day, in the evaluator's order (F6)."""
_LABELS: Final = {
    "current city": "current_city",
    "transportation": "transportation",
    "breakfast": "breakfast",
    "attraction": "attraction",
    "attractions": "attraction",
    "lunch": "lunch",
    "dinner": "dinner",
    "accommodation": "accommodation",
    "accommodations": "accommodation",
}
EMPTY_VALUE: Final = "-"

THINK_WARNING: Final = "think_block_in_output"
DUPLICATE_WARNING: Final = "duplicate_field"
MISSING_WARNING: Final = "missing_field"
SEQUENCE_WARNING: Final = "day_sequence"

FailureReason = Literal["empty_output", "no_day_blocks", "no_fields"]
DayPlan = dict[str, int | str]

_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_FENCE = re.compile(r"^\s*```")
_BULLETS = re.compile(r"^\s*(?:[#*•-]+\s*)+")
_HEADER = re.compile(r"(?i)^\s*day\s*(\d+)\s*:?\s*$")
_FIELD = re.compile(
    r"(?i)^\s*(current city|transportation|breakfast|attractions?|lunch|dinner|accommodations?)"
    r"\s*:\s*(.*)$"
)


@dataclass(frozen=True, slots=True)
class ParsedPlan:
    plan: list[DayPlan] | None
    """The evaluator's plan, or None on a parse failure."""
    failure_reason: FailureReason | None
    warnings: tuple[str, ...]
    thinking_text: str | None
    """The content of the removed ``<think>`` blocks, or None when there were none."""

    @property
    def ok(self) -> bool:
        return self.plan is not None

    @property
    def n_days(self) -> int:
        return len(self.plan) if self.plan is not None else 0


def split_think(text: str) -> tuple[str, str | None]:
    """``text`` without its ``<think>…</think>`` blocks, and their contents joined with a newline
    (None when there are none)."""
    contents = _THINK.findall(text)
    if not contents:
        return text, None
    return _THINK.sub("", text), "\n".join(contents)


def _normalize_line(line: str) -> str | None:
    """One line after step 1, or None for a code-fence line."""
    if _FENCE.match(line):
        return None
    return _BULLETS.sub("", line.replace("**", ""))


def normalize(text: str) -> str:
    """Step 1 without the think-block extraction's bookkeeping: the text the rules run on."""
    visible, _ = split_think(text.replace("\r\n", "\n"))
    lines = (_normalize_line(line) for line in visible.split("\n"))
    return "\n".join(line for line in lines if line is not None)


def _value(pieces: list[str]) -> str:
    joined = " ".join(p.strip() for p in pieces if p.strip())
    return joined.replace("$", "").strip() or EMPTY_VALUE


@dataclass
class _Day:
    number: int
    values: dict[str, list[str]] = field(default_factory=dict)


def parse_plan(text: str) -> ParsedPlan:
    """Parse one visible output text into the evaluator's plan (D2 steps 1 to 6)."""
    warnings: list[str] = []
    _, thinking = split_think(text.replace("\r\n", "\n"))
    if thinking is not None:
        warnings.append(THINK_WARNING)
    normalized = normalize(text)

    def failed(reason: FailureReason) -> ParsedPlan:
        return ParsedPlan(None, reason, tuple(warnings), thinking)

    if not normalized.strip():
        return failed("empty_output")

    days: list[_Day] = []
    current: str | None = None
    fields_seen = False
    for line in normalized.split("\n"):
        if not line.strip():
            continue
        header = _HEADER.match(line)
        if header:
            days.append(_Day(int(header.group(1))))
            current = None
            continue
        if not days:
            continue  # text before the first header
        field_line = _FIELD.match(line)
        if field_line:
            fields_seen = True
            key = _LABELS[field_line.group(1).lower()]
            day = days[-1]
            if key in day.values:
                warnings.append(DUPLICATE_WARNING)
                current = None
            else:
                day.values[key] = [field_line.group(2)]
                current = key
            continue
        if current is not None:
            days[-1].values[current].append(line)

    if not days:
        return failed("no_day_blocks")
    if not fields_seen:
        return failed("no_fields")

    plan: list[DayPlan] = []
    for day in days:
        entry: DayPlan = {"days": day.number}
        for name in FIELDS:
            if name in day.values:
                entry[name] = _value(day.values[name])
            else:
                entry[name] = EMPTY_VALUE
                warnings.append(f"{MISSING_WARNING}:{name}")
        plan.append(entry)
    if [day.number for day in days] != list(range(1, len(days) + 1)):
        warnings.append(SEQUENCE_WARNING)
    return ParsedPlan(plan, None, tuple(warnings), thinking)
