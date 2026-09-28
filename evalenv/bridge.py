"""Evaluator bridge (ARCHITECTURE.md D5 §Bridge). Owner: data-eval.

A long-lived subprocess that runs the vendored TravelPlanner evaluator, unmodified, in the
``evalenv`` environment. It is started by ``tripartite.evaluation.bridge_client.RealBridge`` as

    uv run --project <repo>/evalenv python <repo>/evalenv/bridge.py

with ``cwd=vendor/travelplanner/evaluation`` and
``PYTHONPATH=vendor/travelplanner:vendor/travelplanner/evaluation``. It uses the standard
library and the vendored modules only, and never imports ``tripartite``.

**Protocol.** JSON Lines: one request object per line on stdin, one response object per line
on stdout, in order. Logs, tracebacks and everything the evaluator prints go to stderr: the
evaluator's tool classes print on import ("Flights API loaded.") and one check prints while
it runs, so the protocol channel is a private duplicate of the original stdout, and file
descriptor 1 is pointed at stderr before the evaluator is imported. The database CSVs load
once per process, when ``eval`` is imported at start-up.

- ``{"op": "per_plan", "id", "query": <bridge row>, "plan": <list | null>}`` returns
  ``{"id", "delivered", "commonsense": {key: [value, message]}, "hard": {...} | null}``.
  Before evaluating, the one conversion ``eval.py`` applies (lines 74-75) is applied to the
  row: a string ``local_constraint`` becomes ``ast.literal_eval(local_constraint)``. The hard
  checks run only when ``is_not_absent`` and ``is_valid_information_in_sandbox`` both pass,
  exactly as ``eval.py`` gates them. A null or empty plan returns ``delivered: false`` with
  both groups null.
- ``{"op": "aggregate", "id", "set_type": "validation", "plans_path", "records_path"}``
  returns ``{"id", "scores", "detailed"}`` from ``eval.eval_score``. The module attribute
  ``eval.load_dataset`` is replaced, for the duration of the call, by a function that returns
  the records file's rows, so the ``force_redownload`` network call never happens (F2). No
  vendored file is edited, and nothing is converted: ``eval.py`` converts ``local_constraint``
  itself. Any ``set_type`` other than ``validation`` is refused.
- Any exception returns ``{"id", "error": {"type", "message"}}`` (traceback on stderr), and
  the bridge carries on with the next request. It exits 0 at the end of stdin.

A bridge row is exactly what ``datasets.load_dataset`` returns per row (D5 §Bridge records
file): the 11 validation columns, ``days``, ``visiting_city_number``, ``people_number`` and
``budget`` as integers, every other column as its verbatim string.
"""

import ast
import copy
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO

COLUMNS = (
    "org",
    "dest",
    "days",
    "visiting_city_number",
    "date",
    "people_number",
    "local_constraint",
    "budget",
    "query",
    "level",
    "reference_information",
)
INT_COLUMNS = frozenset({"days", "visiting_city_number", "people_number", "budget"})
N_VALIDATION = 180
DATASET = ("osunlp/TravelPlanner", "validation")


class BadRequestError(ValueError):
    """The request is malformed."""


class TestSplitForbiddenError(RuntimeError):
    """The test split is never evaluated (D3)."""


def log(message: str) -> None:
    print(f"bridge: {message}", file=sys.stderr, flush=True)


def check_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != set(COLUMNS):
        keys = sorted(row) if isinstance(row, dict) else type(row).__name__
        raise BadRequestError(f"a bridge row has exactly the keys {list(COLUMNS)}, got {keys}")
    for column, value in row.items():
        expected = int if column in INT_COLUMNS else str
        if type(value) is not expected:
            raise BadRequestError(f"{column} must be {expected.__name__}, got {value!r}")
    return row


def result_group(box: Any) -> dict[str, list[Any]]:
    """An evaluator result dict as ``{key: [value, message]}``, values true, false or null."""
    if not isinstance(box, dict):
        raise TypeError(f"expected a dict of results, got {box!r}")
    group = {}
    for key, pair in box.items():
        if not isinstance(pair, tuple | list) or len(pair) != 2:
            raise TypeError(f"{key}: expected (value, message), got {pair!r}")
        value, message = pair
        if value is not None and not isinstance(value, bool):
            if type(value).__name__ != "bool_":  # numpy.bool_, compared like a bool upstream
                raise TypeError(f"{key}: value {value!r} is not a bool or None")
            value = bool(value)
        if message is not None and not isinstance(message, str):
            raise TypeError(f"{key}: message {message!r} is not a str or None")
        group[key] = [value, message]
    return group


class Evaluator:
    def __init__(self) -> None:
        started = time.monotonic()
        # eval.py imports both constraint modules, which load the database CSVs.
        self.eval: ModuleType = importlib.import_module("eval")
        self.commonsense: ModuleType = importlib.import_module("commonsense_constraint")
        self.hard: ModuleType = importlib.import_module("hard_constraint")
        log(
            f"evaluator loaded in {time.monotonic() - started:.1f} s from {Path.cwd()}; "
            f"HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')} "
            f"HF_DATASETS_OFFLINE={os.environ.get('HF_DATASETS_OFFLINE')}"
        )

    def per_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        query = copy.deepcopy(check_row(request.get("query")))
        plan = request.get("plan")
        if plan is not None and not isinstance(plan, list):
            raise BadRequestError(f"plan must be a list or null, got {type(plan).__name__}")
        if not plan:
            return {"delivered": False, "commonsense": None, "hard": None}
        if isinstance(query["local_constraint"], str):
            query["local_constraint"] = ast.literal_eval(query["local_constraint"])
        commonsense = self.commonsense.evaluation(query, plan)
        hard = None
        if (
            commonsense
            and commonsense["is_not_absent"][0]
            and commonsense["is_valid_information_in_sandbox"][0]
        ):
            hard = self.hard.evaluation(query, plan)
        return {
            "delivered": True,
            "commonsense": result_group(commonsense),
            "hard": result_group(hard) if hard is not None else None,
        }

    def aggregate(self, request: dict[str, Any]) -> dict[str, Any]:
        set_type = request.get("set_type")
        if isinstance(set_type, str) and set_type.strip().lower() == "test":
            raise TestSplitForbiddenError("the test split is never evaluated (D3)")
        if set_type != "validation":
            raise BadRequestError(f"unsupported set_type {set_type!r}: only 'validation'")
        paths = {}
        for field in ("plans_path", "records_path"):
            value = request.get(field)
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise BadRequestError(f"{field} must be an absolute path, got {value!r}")
            paths[field] = value
        lines = Path(paths["records_path"]).read_bytes().split(b"\n")
        if lines[-1] == b"":
            lines.pop()
        if len(lines) != N_VALIDATION:
            raise BadRequestError(f"records_path has {len(lines)} rows, expected {N_VALIDATION}")
        records = [check_row(json.loads(line.decode("utf-8"))) for line in lines]

        def load_dataset(path: str, name: str, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
            if (path, name) != DATASET:
                raise RuntimeError(f"unexpected load_dataset({path!r}, {name!r})")
            return {"validation": copy.deepcopy(records)}

        original = self.eval.load_dataset
        self.eval.load_dataset = load_dataset
        try:
            scores, detailed = self.eval.eval_score("validation", paths["plans_path"])
        finally:
            self.eval.load_dataset = original
        return {"scores": scores, "detailed": detailed}


def handle(evaluator: Evaluator, line: bytes) -> str:
    """The response line for one request line, without the newline."""
    request_id = None
    try:
        request = json.loads(line.decode("utf-8"))
        if not isinstance(request, dict):
            raise BadRequestError("a request must be a JSON object")
        request_id = request.get("id")
        op = request.get("op")
        if op == "per_plan":
            body = evaluator.per_plan(request)
        elif op == "aggregate":
            body = evaluator.aggregate(request)
        else:
            raise BadRequestError(f"unknown op {op!r}")
        return json.dumps({"id": request_id, **body}, ensure_ascii=False, allow_nan=False)
    except Exception as exc:  # the bridge reports every evaluator failure and carries on
        traceback.print_exc(file=sys.stderr)
        error = {"type": type(exc).__name__, "message": str(exc)}
        return json.dumps({"id": request_id, "error": error}, ensure_ascii=False)


def open_protocol_channel() -> TextIO:
    """A private duplicate of stdout for responses; fd 1 and ``sys.stdout`` then go to stderr."""
    sys.stdout.flush()
    channel = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return channel


def main() -> int:
    channel = open_protocol_channel()
    try:
        evaluator = Evaluator()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        log("could not load the evaluator; exiting")
        return 1
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        channel.write(handle(evaluator, line) + "\n")
        channel.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
