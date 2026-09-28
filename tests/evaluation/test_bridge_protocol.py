"""The real ``evalenv/bridge.py`` and ``RealBridge``, over stub evaluator modules (D5 §Bridge).

CI has no database and no ``evalenv``, but the bridge itself is standard library only. These
tests run it under this environment's Python, with ``PYTHONPATH`` pointing at stand-ins for
``eval``, ``commonsense_constraint`` and ``hard_constraint`` written into ``tmp_path``. The
stubs print to stdout on import and while evaluating, as the real modules do, and ``eval``'s
own ``load_dataset`` raises, as a network call would be refused.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tripartite.evaluation.bridge_client import (
    BRIDGE_SCRIPT,
    BridgeError,
    EvaluationError,
    RealBridge,
)
from tripartite.evaluation.constraints import COMMONSENSE_KEYS, HARD_KEYS
from tripartite.evaluation.records import (
    EvalRecord,
    load_eval_records,
    to_bridge_row,
    write_bridge_records,
)
from tripartite.runlog.schema import OFFICIAL_METRIC_KEYS

COMMONSENSE_STUB = f"""
print("Flights API loaded.")  # the real tool classes print on import
KEYS = {list(COMMONSENSE_KEYS)!r}


def evaluation(query, plan):
    print("noise while evaluating")
    marker = plan[0].get("marker", "pass")
    if marker == "boom":
        raise KeyError("stub evaluator crash")
    if marker == "load_dataset":
        import eval
        eval.load_dataset("osunlp/TravelPlanner", "validation")
    box = {{key: (True, None) for key in KEYS}}
    kind = type(query["local_constraint"]).__name__
    box["is_valid_restaurants"] = (True, "local_constraint is a " + kind)
    if marker == "gated":
        box["is_valid_information_in_sandbox"] = (False, "The lunch in day 1 is invalid.")
    if marker == "bad_value":
        box["is_not_absent"] = ("yes", None)
    return box
"""
HARD_STUB = f"""
KEYS = {list(HARD_KEYS)!r}


def evaluation(query, plan):
    cuisine = query["local_constraint"]["cuisine"]
    return {{key: (None, None) if key == "valid_cuisine" and cuisine is None else (True, None)
            for key in KEYS}}
"""
EVAL_STUB = f"""
import json
from commonsense_constraint import evaluation as commonsense_eval
from hard_constraint import evaluation as hard_eval

print("eval stub imported")


def load_dataset(*args, **kwargs):
    raise RuntimeError("the network load_dataset was called")


def eval_score(set_type, file_path):
    rows = load_dataset("osunlp/TravelPlanner", "validation", download_mode="force_redownload")
    rows = rows["validation"]
    plans = [json.loads(line) for line in open(file_path).read().strip().split("\\n")]
    print("scoring", len(rows))
    delivered = sum(1 for p in plans if p["plan"])
    scores = {{key: 0.0 for key in {list(OFFICIAL_METRIC_KEYS)!r}}}
    scores["Delivery Rate"] = delivered / 180
    kinds = sorted({{type(r["local_constraint"]).__name__ for r in rows}})
    return scores, {{"kinds": kinds, "n": len(rows), "by_day": {{3: 1, 5: 2}}}}
"""


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    directory = tmp_path / "evaluation"
    directory.mkdir()
    (directory / "commonsense_constraint.py").write_text(COMMONSENSE_STUB)
    (directory / "hard_constraint.py").write_text(HARD_STUB)
    (directory / "eval.py").write_text(EVAL_STUB)
    return directory


def _stub_bridge(stubs: Path) -> RealBridge:
    """The real bridge script under this Python, importing the stubs instead of the evaluator."""
    return RealBridge(command=[sys.executable, str(BRIDGE_SCRIPT)], cwd=stubs, pythonpath=[stubs])


@pytest.fixture
def bridge(stubs: Path) -> Iterator[RealBridge]:
    with _stub_bridge(stubs) as b:
        yield b


@pytest.fixture
def records(synthetic_raw: Path) -> list[EvalRecord]:
    return load_eval_records()


def _raw(stubs: Path, requests: list[bytes]) -> tuple[list[dict[str, Any]], int]:
    """Send raw request lines to a fresh bridge; return its responses and exit code."""
    env = {**os.environ, "PYTHONPATH": str(stubs), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, str(BRIDGE_SCRIPT)],
        input=b"".join(line + b"\n" for line in requests),
        cwd=stubs,
        env=env,
        capture_output=True,
        check=False,
    )
    return [json.loads(line) for line in result.stdout.splitlines()], result.returncode


def _plans_file(path: Path, plans: list[Any]) -> Path:
    path.write_text("".join(json.dumps({"idx": i, "plan": p}) + "\n" for i, p in enumerate(plans)))
    return path


def test_an_empty_plan_is_not_delivered(bridge: RealBridge, records: list[EvalRecord]) -> None:
    for plan in (None, []):
        result = bridge.per_plan(records[0], plan)

        assert (result.delivered, result.commonsense, result.hard) == (False, None, None)


def test_a_delivered_plan_is_evaluated_with_local_constraint_converted(
    bridge: RealBridge, records: list[EvalRecord]
) -> None:
    result = bridge.per_plan(records[0], [{"days": 1}])

    assert result.delivered
    assert result.commonsense is not None
    assert result.commonsense["is_valid_restaurants"] == (True, "local_constraint is a dict")
    assert result.hard is not None
    assert result.hard["valid_cuisine"] == (True, None)  # row 1 has a cuisine constraint
    assert bridge.per_plan(records[1], [{"days": 1}]).hard["valid_cuisine"] == (None, None)  # type: ignore[index]


def test_the_hard_group_is_gated_as_in_eval_py(
    bridge: RealBridge, records: list[EvalRecord]
) -> None:
    result = bridge.per_plan(records[0], [{"marker": "gated"}])

    assert result.commonsense is not None
    assert result.commonsense["is_valid_information_in_sandbox"][0] is False
    assert result.hard is None


def test_an_evaluator_exception_is_reported_and_the_bridge_carries_on(
    bridge: RealBridge, records: list[EvalRecord]
) -> None:
    with pytest.raises(EvaluationError) as info:
        bridge.per_plan(records[0], [{"marker": "boom"}])

    assert info.value.error_type == "KeyError"
    assert "stub evaluator crash" in info.value.message
    assert bridge.per_plan(records[0], [{"days": 1}]).delivered


def test_a_non_boolean_check_value_is_an_evaluation_error(
    bridge: RealBridge, records: list[EvalRecord]
) -> None:
    with pytest.raises(EvaluationError, match="is not a bool or None"):
        bridge.per_plan(records[0], [{"marker": "bad_value"}])


def test_aggregate_replaces_load_dataset_and_converts_nothing(
    bridge: RealBridge, records: list[EvalRecord], tmp_path: Path
) -> None:
    records_path = tmp_path / "records.jsonl"
    write_bridge_records(records, records_path)
    plans = _plans_file(tmp_path / "plans.jsonl", [[{"days": 1}]] * 161 + [None] * 19)

    metrics = bridge.aggregate(plans, records_path)

    assert metrics.scores["Delivery Rate"] == 161 / 180
    assert metrics.detailed == {"kinds": ["str"], "n": 180, "by_day": {"3": 1, "5": 2}}
    # Restored afterwards: the module's own load_dataset raises again.
    with pytest.raises(EvaluationError, match="the network load_dataset was called"):
        bridge.per_plan(records[0], [{"marker": "load_dataset"}])
    assert bridge.aggregate(plans, records_path).scores == metrics.scores


def test_the_bridge_refuses_what_d5_refuses(
    stubs: Path, records: list[EvalRecord], tmp_path: Path
) -> None:
    good = tmp_path / "records.jsonl"
    write_bridge_records(records, good)
    short = tmp_path / "short.jsonl"
    write_bridge_records(records[:179], short)
    plans = str(_plans_file(tmp_path / "plans.jsonl", [None] * 180))
    row = to_bridge_row(records[0])

    def aggregate(**fields: Any) -> bytes:
        request = {"op": "aggregate", "set_type": "validation", "plans_path": plans}
        return json.dumps({**request, "records_path": str(good), **fields}).encode()

    requests = [
        aggregate(id=1, set_type="test"),
        aggregate(id=2, set_type="train"),
        aggregate(id=3, records_path=str(short)),
        aggregate(id=4, plans_path="plans.jsonl"),
        json.dumps({"op": "per_plan", "id": 5, "query": {**row, "days": "3"}, "plan": []}).encode(),
        json.dumps({"op": "per_plan", "id": 6, "query": {**row, "id": 1}, "plan": []}).encode(),
        json.dumps({"op": "per_plan", "id": 7, "query": row, "plan": {"days": 1}}).encode(),
        json.dumps({"op": "unknown", "id": 8}).encode(),
        b"not json",
        aggregate(id=10),
    ]
    responses, code = _raw(stubs, requests)

    assert code == 0
    errors = [(r["id"], r.get("error", {}).get("type")) for r in responses]
    assert errors == [
        (1, "TestSplitForbiddenError"),
        (2, "BadRequestError"),
        (3, "BadRequestError"),
        (4, "BadRequestError"),
        (5, "BadRequestError"),
        (6, "BadRequestError"),
        (7, "BadRequestError"),
        (8, "BadRequestError"),
        (None, "JSONDecodeError"),
        (10, None),
    ]
    assert "179 rows, expected 180" in responses[2]["error"]["message"]
    assert set(responses[-1]["scores"]) == set(OFFICIAL_METRIC_KEYS)


def test_nothing_but_responses_reaches_stdout(stubs: Path, records: list[EvalRecord]) -> None:
    request = {"op": "per_plan", "id": "a", "query": to_bridge_row(records[0]), "plan": [{}]}

    responses, code = _raw(stubs, [json.dumps(request).encode()])

    assert code == 0
    assert [r["id"] for r in responses] == ["a"]  # the stubs' prints went to stderr


def test_a_bridge_that_cannot_load_the_evaluator_fails_loudly(
    stubs: Path, records: list[EvalRecord]
) -> None:
    (stubs / "eval.py").write_text("raise FileNotFoundError('../database/flights/x.csv')\n")

    with (
        _stub_bridge(stubs) as b,
        pytest.raises(BridgeError, match="exited with code 1 before answering"),
    ):
        b.per_plan(records[0], None)


def test_a_response_to_another_request_is_refused(
    tmp_path: Path, records: list[EvalRecord]
) -> None:
    liar = tmp_path / "liar.py"
    liar.write_text(
        "import sys\nfor line in sys.stdin:\n"
        '    print(\'{"id": 99, "delivered": false}\', flush=True)\n'
    )

    with (
        RealBridge(command=[sys.executable, str(liar)], cwd=tmp_path, pythonpath=[]) as b,
        pytest.raises(BridgeError, match="expected a response to request 1"),
    ):
        b.per_plan(records[0], None)
