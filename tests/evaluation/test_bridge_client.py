"""The bridge client (ARCHITECTURE.md D5 §Wrapper): ``FakeBridge``, ``bridge_from_env``, the
``RealBridge`` command and environment, and the response checks. No subprocess runs here."""

import json
from pathlib import Path
from typing import Any

import pytest

from tripartite.data.manifest import REPO_ROOT
from tripartite.evaluation.bridge_client import (
    BridgeError,
    FakeBridge,
    RealBridge,
    bridge_from_env,
    parse_metrics,
    parse_per_plan,
)
from tripartite.evaluation.constraints import COMMONSENSE_KEYS, HARD_KEYS, PerPlanResult
from tripartite.evaluation.records import EvalRecord, load_eval_records, write_bridge_records
from tripartite.runlog.schema import OFFICIAL_METRIC_KEYS


@pytest.fixture
def records(synthetic_raw: Path) -> list[EvalRecord]:
    return load_eval_records()


def _plans_file(path: Path, plans: list[Any]) -> Path:
    path.write_text("".join(json.dumps({"idx": i, "plan": p}) + "\n" for i, p in enumerate(plans)))
    return path


# --- FakeBridge -----------------------------------------------------------------------------


def test_the_fake_bridge_does_not_deliver_an_empty_plan(records: list[EvalRecord]) -> None:
    for plan in (None, []):
        result = FakeBridge().per_plan(records[0], plan)

        assert result == PerPlanResult("val-001", False, None, None)


def test_the_fake_bridge_passes_every_applicable_check(records: list[EvalRecord]) -> None:
    with_constraints = FakeBridge().per_plan(records[0], [{"days": 1}])  # odd rows: canaries
    without = FakeBridge().per_plan(records[1], [{"days": 1}])  # even rows: all None

    assert with_constraints.commonsense == dict.fromkeys(COMMONSENSE_KEYS, (True, None))
    assert with_constraints.hard == {
        "valid_cost": (True, None),
        "valid_room_rule": (True, None),
        "valid_cuisine": (True, None),
        "valid_room_type": (None, None),  # 'room type': None in the synthetic set
        "valid_transportation": (True, None),
    }
    assert without.hard == {key: (None, None) for key in HARD_KEYS} | {"valid_cost": (True, None)}


def test_the_fake_bridge_returns_the_results_it_was_given(records: list[EvalRecord]) -> None:
    given = PerPlanResult("val-002", True, dict.fromkeys(COMMONSENSE_KEYS, (False, "x")), None)

    bridge = FakeBridge({"val-002": given})

    assert bridge.per_plan(records[1], [{"days": 1}]) is given
    assert bridge.per_plan(records[0], None).delivered is False


def test_the_fake_aggregate_scores_the_files_it_is_given(
    records: list[EvalRecord], tmp_path: Path
) -> None:
    records_path = tmp_path / "records.jsonl"
    write_bridge_records(records, records_path)
    plans = _plans_file(tmp_path / "plans.jsonl", [[{"days": 1}]] * 90 + [None] * 90)
    # The synthetic levels are canaries; give aggregate real cells to count.
    rows = [json.loads(line) for line in records_path.read_text().splitlines()]
    for i, row in enumerate(rows):
        row["level"] = "easy"
        row["local_constraint"] = str(
            dict.fromkeys(("house rule", "cuisine", "room type", "transportation"))
        )
        row["days"] = (3, 5, 7)[i % 3]
    records_path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    with FakeBridge() as bridge:
        metrics = bridge.aggregate(plans, records_path)

    assert metrics.scores == {
        "Delivery Rate": 0.5,
        "Commonsense Constraint Micro Pass Rate": 0.5,
        "Commonsense Constraint Macro Pass Rate": 0.5,
        "Hard Constraint Micro Pass Rate": 0.5,
        "Hard Constraint Macro Pass Rate": 0.5,
        "Final Pass Rate": 0.5,
    }


def test_the_fake_aggregate_refuses_a_short_records_file(
    records: list[EvalRecord], tmp_path: Path
) -> None:
    records_path = tmp_path / "records.jsonl"
    write_bridge_records(records[:10], records_path)
    plans = _plans_file(tmp_path / "plans.jsonl", [None] * 180)

    with pytest.raises(ValueError, match="10 rows, expected 180"):
        FakeBridge().aggregate(plans, records_path)


# --- bridge_from_env ------------------------------------------------------------------------


def test_the_fake_mode_variable_selects_the_fake_bridge() -> None:
    assert isinstance(bridge_from_env(), FakeBridge)  # CI sets TRIPARTITE_EVAL_BRIDGE=fake


@pytest.mark.parametrize("value", [None, "real"])
def test_unset_or_real_selects_the_real_bridge(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if value is None:
        monkeypatch.delenv("TRIPARTITE_EVAL_BRIDGE")
    else:
        monkeypatch.setenv("TRIPARTITE_EVAL_BRIDGE", value)

    bridge = bridge_from_env()

    assert isinstance(bridge, RealBridge)
    bridge.close()  # never started: construction spawns nothing


def test_any_other_mode_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPARTITE_EVAL_BRIDGE", "fast")

    with pytest.raises(ValueError, match="TRIPARTITE_EVAL_BRIDGE must be 'real' or 'fake'"):
        bridge_from_env()


# --- RealBridge: D5's command and the child environment --------------------------------------


def test_the_real_bridge_runs_d5s_command_with_absolute_paths() -> None:
    assert RealBridge.default_command() == [
        "uv",
        "run",
        "--locked",
        "--project",
        str(REPO_ROOT / "evalenv"),
        "python",
        str(REPO_ROOT / "evalenv" / "bridge.py"),
    ]


def test_the_child_environment_is_offline_and_leaves_the_vendor_tree_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", str(REPO_ROOT / ".venv"))
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")

    env = RealBridge().child_env()

    vendor = REPO_ROOT / "vendor" / "travelplanner"
    assert env["PYTHONPATH"] == f"{vendor}:{vendor / 'evaluation'}"
    assert env["HF_HUB_OFFLINE"] == env["HF_DATASETS_OFFLINE"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["GRADIO_ANALYTICS_ENABLED"] == "False"
    assert "VIRTUAL_ENV" not in env


# --- response checks (A-014) ----------------------------------------------------------------


def _response(**changes: Any) -> dict[str, Any]:
    response = {
        "delivered": True,
        "commonsense": {k: [True, None] for k in COMMONSENSE_KEYS},
        "hard": {k: [None, None] for k in HARD_KEYS},
    }
    return {**response, **changes}


def test_a_well_formed_response_parses() -> None:
    result = parse_per_plan("val-001", _response())

    assert result.commonsense == dict.fromkeys(COMMONSENSE_KEYS, (True, None))
    assert result.hard == dict.fromkeys(HARD_KEYS, (None, None))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"delivered": "yes"}, "delivered must be a bool"),
        ({"commonsense": {"is_not_absent": [True, None]}}, "expected exactly the checks"),
        ({"hard": {k: [None, None] for k in HARD_KEYS[1:]}}, "expected exactly the checks"),
        ({"hard": {k: [1, None] for k in HARD_KEYS}}, r"expected \[true\|false\|null"),
        ({"hard": {k: [True, 3] for k in HARD_KEYS}}, r"expected \[true\|false\|null"),
        ({"hard": {k: [True] for k in HARD_KEYS}}, r"expected \[true\|false\|null"),
        ({"commonsense": None}, "commonsense must be present exactly when delivered"),
        ({"delivered": False}, "commonsense must be present exactly when delivered"),
        ({"delivered": False, "commonsense": None}, "hard results without commonsense"),
    ],
)
def test_a_malformed_response_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(BridgeError, match=message):
        parse_per_plan("val-001", _response(**changes))


def test_metrics_need_the_six_official_keys_and_a_detailed_object() -> None:
    scores = dict.fromkeys(OFFICIAL_METRIC_KEYS, 0.5)

    assert parse_metrics({"scores": scores, "detailed": {}}).scores == scores
    with pytest.raises(BridgeError, match="scores must have exactly"):
        parse_metrics({"scores": {"Delivery Rate": 1.0}, "detailed": {}})
    with pytest.raises(BridgeError, match="scores must be numbers"):
        parse_metrics({"scores": dict.fromkeys(OFFICIAL_METRIC_KEYS, "0.5"), "detailed": {}})
    with pytest.raises(BridgeError, match="detailed must be an object"):
        parse_metrics({"scores": scores, "detailed": None})
