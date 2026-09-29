"""D2 golden test 7(b): hand-written fixtures for every rule and warning of ``rule-text`` ``v1``.

Every text here is written by hand for this test, with invented names; none is model output and
none quotes the sandbox database (§8). The round trip over the upstream example plans (7a) is in
``test_round_trip.py``.
"""

import inspect

import pytest

from tripartite.parse.text_plan_parser import (
    FIELDS,
    PARSER_VERSION_ID,
    ParsedPlan,
    normalize,
    parse_plan,
    split_think,
)

DAY_1 = """Day 1:
Current City: from Aville to Synthville
Transportation: Flight Number: F0000001, from Aville to Synthville, Departure Time: 08:00
Breakfast: -
Attraction: Synth Museum, Synthville;Synth Park, Synthville;
Lunch: Cafe One, Synthville
Dinner: Diner Two, Synthville
Accommodation: Cozy Room, Synthville"""

DAY_1_PLAN = {
    "days": 1,
    "current_city": "from Aville to Synthville",
    "transportation": "Flight Number: F0000001, from Aville to Synthville, Departure Time: 08:00",
    "breakfast": "-",
    "attraction": "Synth Museum, Synthville;Synth Park, Synthville;",
    "lunch": "Cafe One, Synthville",
    "dinner": "Diner Two, Synthville",
    "accommodation": "Cozy Room, Synthville",
}


LABELS = {
    "current_city": "Current City",
    "transportation": "Transportation",
    "breakfast": "Breakfast",
    "attraction": "Attraction",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "accommodation": "Accommodation",
}


def day(number: int, *, skip: tuple[str, ...] = (), **values: str) -> str:
    """A day block in the official format, every field ``x<field>`` unless given; the fields in
    ``skip`` are left out."""
    lines = [f"Day {number}:"]
    lines += [f"{LABELS[f]}: {values.get(f, 'x' + f)}" for f in FIELDS if f not in skip]
    return "\n".join(lines)


def expected_day(number: int, **values: str) -> dict[str, int | str]:
    return {"days": number, **{f: values.get(f, "x" + f) for f in FIELDS}}


def only(result: ParsedPlan) -> list[dict[str, int | str]]:
    assert result.plan is not None, result
    return result.plan


def test_the_parser_id_and_version() -> None:
    assert PARSER_VERSION_ID == "rule-text/v1"


def test_the_official_format_parses_with_every_value_verbatim() -> None:
    result = parse_plan(DAY_1 + "\n\n" + day(2) + "\n")

    assert result.ok
    assert result.failure_reason is None
    assert result.plan == [DAY_1_PLAN, expected_day(2)]
    assert result.warnings == ()
    assert result.thinking_text is None
    assert result.n_days == 2


def test_each_day_has_exactly_the_evaluator_keys_in_order() -> None:
    plan = only(parse_plan(day(1)))

    assert list(plan[0]) == ["days", *FIELDS]
    assert FIELDS == (
        "current_city",
        "transportation",
        "breakfast",
        "attraction",
        "lunch",
        "dinner",
        "accommodation",
    )


def test_the_parser_reads_only_the_text() -> None:
    """D2: input is the visible output text only; no query or evaluator field can reach it."""
    assert list(inspect.signature(parse_plan).parameters) == ["text"]


# --- rule 1: normalization -----------------------------------------------------------------


def test_crlf_parses_like_lf() -> None:
    text = DAY_1 + "\n\n" + day(2)

    assert parse_plan(text.replace("\n", "\r\n")) == parse_plan(text)


def test_a_think_block_is_removed_and_kept_as_thinking_text() -> None:
    result = parse_plan("<think>\nweigh the budget\n</think>\n" + DAY_1)

    assert result.plan == [DAY_1_PLAN]
    assert result.thinking_text == "\nweigh the budget\n"
    assert result.warnings == ("think_block_in_output",)


def test_every_think_block_is_removed_and_their_contents_joined() -> None:
    result = parse_plan("<think>a</think>" + DAY_1 + "<think>b</think>\n")

    assert result.plan == [DAY_1_PLAN]
    assert result.thinking_text == "a\nb"
    assert result.warnings == ("think_block_in_output",)


def test_a_think_block_inside_a_value_is_removed_from_it() -> None:
    result = parse_plan(day(1, lunch="Cafe<think>hmm</think> One"))

    assert only(result)[0]["lunch"] == "Cafe One"
    assert result.thinking_text == "hmm"


def test_an_unclosed_think_tag_is_left_as_text() -> None:
    result = parse_plan("<think> never closed\n" + DAY_1)

    assert result.plan == [DAY_1_PLAN]  # the tag sits before the first header
    assert result.thinking_text is None
    assert result.warnings == ()


def test_code_fence_lines_are_removed() -> None:
    result = parse_plan("```text\n" + DAY_1 + "\n```\n```\n")

    assert result.plan == [DAY_1_PLAN]


def test_double_asterisks_are_removed_everywhere() -> None:
    text = "**Day 1:**\n" + "\n".join(DAY_1.splitlines()[1:]).replace(
        "Lunch: Cafe One", "**Lunch:** Cafe **One**"
    )

    assert parse_plan(text).plan == [DAY_1_PLAN]


@pytest.mark.parametrize("marker", ["#", "###", "-", "*", "•", "- ", "* ", "• ", "## -", "- *"])
def test_leading_bullet_markers_are_removed(marker: str) -> None:
    text = f"{marker} Day 1:\n" + "\n".join(f"{marker} {line}" for line in DAY_1.splitlines()[1:])

    assert parse_plan(text).plan == [DAY_1_PLAN]


def test_bullet_markers_are_removed_only_at_line_start() -> None:
    plan = only(parse_plan(day(1, accommodation="*Quiet* Loft - with #view, Synthville")))

    assert plan[0]["accommodation"] == "*Quiet* Loft - with #view, Synthville"


def test_normalize_is_step_one_only() -> None:
    assert normalize("a\r\n**b**\n```\n- c\n<think>t</think>d") == "a\nb\nc\nd"


# --- rule 2: day headers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "number"),
    [
        ("Day 1:", 1),
        ("day 1", 1),
        ("DAY 2 :", 2),
        ("Day3:", 3),
        ("  Day 4  ", 4),
        ("Day 05:", 5),
        ("Day\t6:", 6),
    ],
)
def test_day_headers(header: str, number: int) -> None:
    text = "\n".join([header, *day(number).splitlines()[1:]])

    assert only(parse_plan(text)) == [expected_day(number)]


@pytest.mark.parametrize(
    "header", ["Day 1: from Aville to Synthville", "Day one:", "The Day 1:", "Day 1::", "Day -1:"]
)
def test_lines_that_are_not_day_headers(header: str) -> None:
    text = "\n".join([header, *day(1).splitlines()[1:]])

    assert parse_plan(text).failure_reason == "no_day_blocks"


def test_text_before_the_first_header_is_ignored() -> None:
    text = "Here is your plan.\nCurrent City: ignored\nLunch: ignored\n\n" + DAY_1

    assert parse_plan(text).plan == [DAY_1_PLAN]


# --- rule 3: field lines and continuations -----------------------------------------------------


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Current City", "current_city"),
        ("current city", "current_city"),
        ("CURRENT CITY", "current_city"),
        ("Transportation", "transportation"),
        ("Breakfast", "breakfast"),
        ("Attraction", "attraction"),
        ("Attractions", "attraction"),
        ("Lunch", "lunch"),
        ("Dinner", "dinner"),
        ("Accommodation", "accommodation"),
        ("accommodations", "accommodation"),
    ],
)
def test_every_label_spelling(label: str, key: str) -> None:
    text = day(1, skip=(key,)) + f"\n  {label}  :  value of {key}  "

    result = parse_plan(text)
    assert only(result) == [expected_day(1, **{key: f"value of {key}"})]
    assert result.warnings == ()


def test_a_non_field_line_continues_the_previous_field_space_joined() -> None:
    text = day(1).replace(
        "Attraction: xattraction",
        "Attraction: Synth Museum, Synthville;\nSynth Park, Synthville;\n\n  Lake;  ",
    )

    plan = only(parse_plan(text))
    assert plan[0]["attraction"] == "Synth Museum, Synthville; Synth Park, Synthville; Lake;"
    assert plan[0]["lunch"] == "xlunch"


def test_a_continuation_fills_an_empty_field_line() -> None:
    text = day(1).replace("Attraction: xattraction", "Attraction:\n- Synth Museum;\n- Synth Park;")

    assert only(parse_plan(text))[0]["attraction"] == "Synth Museum; Synth Park;"


def test_a_line_before_any_field_of_its_day_is_dropped() -> None:
    text = day(1).replace("Day 1:", "Day 1:\nA lovely first day.")

    result = parse_plan(text)
    assert result.plan == [expected_day(1)]
    assert result.warnings == ()


def test_a_repeated_label_keeps_the_first_and_warns() -> None:
    text = day(1) + "\nLunch: second lunch\nand its continuation\nDinner: second dinner"

    result = parse_plan(text)
    assert result.plan == [expected_day(1)]
    assert result.warnings == ("duplicate_field", "duplicate_field")


def test_labels_repeat_freely_across_days() -> None:
    result = parse_plan(day(1) + "\n" + day(2))

    assert result.warnings == ()


# --- rule 4: values ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("Cafe One, Synthville; Cost: $14", "Cafe One, Synthville; Cost: 14"),
        ("$$ 30", "30"),
        ("$ Cafe $", "Cafe"),
        ("$", "-"),
        ("", "-"),
        ("   ", "-"),
        ("-", "-"),
        ("  padded  ", "padded"),
        ("eat at home", "eat at home"),
        ("Café №1, Sÿnthville ✈", "Café №1, Sÿnthville ✈"),
    ],
)
def test_value_normalization(raw: str, value: str) -> None:
    text = day(1).replace("Lunch: xlunch", f"Lunch: {raw}")

    assert only(parse_plan(text))[0]["lunch"] == value


def test_a_missing_field_becomes_a_dash_and_warns() -> None:
    result = parse_plan(day(1, skip=("attraction", "dinner")))
    assert result.plan == [expected_day(1, attraction="-", dinner="-")]
    assert result.warnings == ("missing_field:attraction", "missing_field:dinner")


def test_a_day_with_no_field_lines_is_kept_with_dashes() -> None:
    result = parse_plan(day(1) + "\nDay 2:\n")

    dashes = dict.fromkeys(FIELDS, "-")
    assert result.plan == [expected_day(1), {"days": 2, **dashes}]
    assert result.warnings == tuple(f"missing_field:{f}" for f in FIELDS)


# --- rule 5: day numbering ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "numbers", [[2, 1], [1, 3], [1, 1], [0, 1], [2, 3, 4]], ids=lambda n: "-".join(map(str, n))
)
def test_non_sequential_days_are_kept_in_order_and_warned_once(numbers: list[int]) -> None:
    result = parse_plan("\n".join(day(n) for n in numbers))

    assert result.plan == [expected_day(n) for n in numbers]
    assert result.warnings == ("day_sequence",)


def test_the_parser_never_pads_or_truncates() -> None:
    for n in (1, 2, 9):
        assert only(parse_plan("\n".join(day(i) for i in range(1, n + 1)))) == [
            expected_day(i) for i in range(1, n + 1)
        ]


# --- rule 6: failures ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty_output"),
        ("  \n\t\n", "empty_output"),
        ("```\n```\n", "empty_output"),
        ("**\n---\n", "empty_output"),
        ("Current City: Synthville\nLunch: Cafe One", "no_day_blocks"),
        ("I cannot plan this trip.", "no_day_blocks"),
        ("Day 1:\nA day in Synthville.\nDay 2:\n", "no_fields"),
        ("Day 1:\n", "no_fields"),
    ],
)
def test_failures(text: str, reason: str) -> None:
    result = parse_plan(text)

    assert result.plan is None
    assert not result.ok
    assert result.n_days == 0
    assert result.failure_reason == reason
    assert result.warnings == ()


def test_a_think_block_alone_is_an_empty_output_that_still_reports_its_thinking() -> None:
    result = parse_plan("<think>\nall of it\n</think>\n")

    assert result.failure_reason == "empty_output"
    assert result.thinking_text == "\nall of it\n"
    assert result.warnings == ("think_block_in_output",)


# --- determinism (R2) and split_think ----------------------------------------------------------


def test_parsing_is_deterministic() -> None:
    text = "<think>x</think>\n### Day 2:\n- **Lunch:** $5\nmore\nLunch: again\nDay 1:\n"

    assert parse_plan(text) == parse_plan(text)


def test_split_think() -> None:
    assert split_think("no tags") == ("no tags", None)
    assert split_think("a<think>b</think>c<think></think>d") == ("acd", "b\n")
    assert split_think("<think>open") == ("<think>open", None)
