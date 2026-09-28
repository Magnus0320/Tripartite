"""The evaluator bridge from the main environment (ARCHITECTURE.md D5 §Bridge, §Wrapper).

``EvaluatorBridge`` has two implementations:

- ``RealBridge`` runs ``evalenv/bridge.py`` as a long-lived subprocess in the ``evalenv``
  environment and speaks its JSON Lines protocol. It starts on first use, and loads the
  database once per process. The command is D5's, with absolute paths, because the bridge's
  cwd is ``vendor/travelplanner/evaluation``::

      uv run --locked --project <repo>/evalenv python <repo>/evalenv/bridge.py

  with ``PYTHONPATH=<repo>/vendor/travelplanner:<repo>/vendor/travelplanner/evaluation``.
  Its environment is this process's, minus ``VIRTUAL_ENV`` (the main environment's), plus
  ``HF_HUB_OFFLINE=1`` and ``HF_DATASETS_OFFLINE=1`` (the evaluator never needs the network;
  ``load_dataset`` is replaced, F2), ``GRADIO_ANALYTICS_ENABLED=False``,
  ``PYTHONDONTWRITEBYTECODE=1`` (nothing is written into ``vendor/``) and ``PYTHONHASHSEED=0``.
- ``FakeBridge`` is the fixture-driven stand-in for CI and the web development loop
  (``TRIPARTITE_EVAL_BRIDGE=fake``). It returns a result passed to it for a query id, or else
  a fixed one: an undelivered plan for a null or empty plan, otherwise every commonsense check
  passed and every applicable hard check passed (null where the query has no such constraint).
  Its ``aggregate`` reads the same two files as the real one and scores them with
  ``tripartite.evaluation.aggregate``.

``bridge_from_env()`` picks one from ``TRIPARTITE_EVAL_BRIDGE`` (``real``, the default, or
``fake``).

Only the validation split is ever evaluated: ``aggregate`` with any other ``set_type`` raises
(``TestSplitForbiddenError`` for ``"test"``) before any file access or subprocess start (D3,
test 4). An exception inside the evaluator raises ``EvaluationError``; the pipeline records the
plan as ``evaluation_error`` and aborts the run, because an evaluator crash is a bug, not a
model failure (D5). A broken bridge process or a malformed response raises ``BridgeError``.
"""

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Final, Protocol, Self, cast

from tripartite.data.manifest import REPO_ROOT
from tripartite.data.planner_inputs import query_id_for, require_validation_split
from tripartite.evaluation.aggregate import LOCAL_CONSTRAINTS, Metrics, aggregate
from tripartite.evaluation.constraints import (
    COMMONSENSE_KEYS,
    HARD_KEYS,
    ConstraintGroup,
    PerPlanResult,
)
from tripartite.evaluation.records import (
    EvalRecord,
    LocalConstraint,
    parse_local_constraint,
    read_bridge_records,
    to_bridge_row,
)
from tripartite.runlog.schema import OFFICIAL_METRIC_KEYS, OfficialMetric

BRIDGE_ENV: Final = "TRIPARTITE_EVAL_BRIDGE"
EVALENV_DIR: Final = REPO_ROOT / "evalenv"
BRIDGE_SCRIPT: Final = EVALENV_DIR / "bridge.py"
VENDOR_DIR: Final = REPO_ROOT / "vendor" / "travelplanner"
EVALUATION_DIR: Final = VENDOR_DIR / "evaluation"
CHILD_ENV: Final = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "GRADIO_ANALYTICS_ENABLED": "False",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
}

Plan = list[dict[str, Any]]


class BridgeError(RuntimeError):
    """The bridge process failed, or broke the protocol."""


class EvaluationError(RuntimeError):
    """The official evaluator raised an exception; the bridge reported it."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(f"{error_type}: {message}")
        self.error_type = error_type
        self.message = message


class EvaluatorBridge(Protocol):
    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult: ...

    def aggregate(
        self, plans_path: Path, records_path: Path, set_type: str = "validation"
    ) -> Metrics: ...

    def close(self) -> None: ...


# --- parsing the bridge's responses ------------------------------------------------------


def _group(value: Any, keys: tuple[str, ...], name: str) -> ConstraintGroup | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(keys):
        found = sorted(value) if isinstance(value, dict) else value
        raise BridgeError(f"{name}: expected exactly the checks {list(keys)}, got {found!r}")
    group: ConstraintGroup = {}
    for key in keys:
        pair = value[key]
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not (pair[0] is None or isinstance(pair[0], bool))
            or not (pair[1] is None or isinstance(pair[1], str))
        ):
            raise BridgeError(f"{name}.{key}: expected [true|false|null, str|null], got {pair!r}")
        group[key] = (pair[0], pair[1])
    return group


def parse_per_plan(query_id: str, response: Mapping[str, Any]) -> PerPlanResult:
    """A ``per_plan`` response as a ``PerPlanResult``, checking its shape (A-014)."""
    delivered = response.get("delivered")
    if not isinstance(delivered, bool):
        raise BridgeError(f"{query_id}: delivered must be a bool, got {delivered!r}")
    result = PerPlanResult(
        query_id=query_id,
        delivered=delivered,
        commonsense=_group(response.get("commonsense"), COMMONSENSE_KEYS, "commonsense"),
        hard=_group(response.get("hard"), HARD_KEYS, "hard"),
    )
    if delivered != (result.commonsense is not None):
        raise BridgeError(f"{query_id}: commonsense must be present exactly when delivered")
    if result.commonsense is None and result.hard is not None:
        raise BridgeError(f"{query_id}: hard results without commonsense results")
    return result


def parse_metrics(response: Mapping[str, Any]) -> Metrics:
    """An ``aggregate`` response as ``Metrics``: the six official keys, verbatim."""
    scores = response.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(OFFICIAL_METRIC_KEYS):
        raise BridgeError(f"scores must have exactly {list(OFFICIAL_METRIC_KEYS)}, got {scores!r}")
    if not all(type(v) is float or type(v) is int for v in scores.values()):
        raise BridgeError(f"scores must be numbers, got {scores!r}")
    detailed = response.get("detailed")
    if not isinstance(detailed, dict):
        raise BridgeError(f"detailed must be an object, got {detailed!r}")
    typed = cast(dict[OfficialMetric, float], {k: float(scores[k]) for k in OFFICIAL_METRIC_KEYS})
    return Metrics(scores=typed, detailed=detailed)


def read_plans(plans_path: Path) -> list[Plan | None]:
    """The ``plan`` of each line of an evaluator plans file, read as ``eval.py`` reads it."""
    lines = plans_path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line)["plan"] for line in lines]


# --- the real bridge ---------------------------------------------------------------------


class RealBridge:
    """``evalenv/bridge.py`` in a subprocess. Use it as a context manager, or call ``close``."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        pythonpath: Sequence[Path] | None = None,
    ) -> None:
        self._command = list(command) if command is not None else self.default_command()
        self._cwd = cwd if cwd is not None else EVALUATION_DIR
        self._pythonpath = (
            list(pythonpath) if pythonpath is not None else [VENDOR_DIR, EVALUATION_DIR]
        )
        self._process: subprocess.Popen[bytes] | None = None
        self._next_id = 0

    @staticmethod
    def default_command() -> list[str]:
        return [
            "uv",
            "run",
            "--locked",
            "--project",
            str(EVALENV_DIR),
            "python",
            str(BRIDGE_SCRIPT),
        ]

    def child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env.update(CHILD_ENV)
        env["PYTHONPATH"] = os.pathsep.join(str(p) for p in self._pythonpath)
        return env

    def _start(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            self._process = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                env=self.child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        return self._process

    def _request(self, op: str, **fields: Any) -> dict[str, Any]:
        process = self._start()
        stdin, stdout = self._pipes(process)
        self._next_id += 1
        request_id = self._next_id
        line = json.dumps({"op": op, "id": request_id, **fields}, ensure_ascii=False)
        try:
            stdin.write(line.encode("utf-8") + b"\n")
            stdin.flush()
        except BrokenPipeError:
            raise BridgeError(f"the bridge exited with code {process.wait()}") from None
        reply = stdout.readline()
        if not reply:
            raise BridgeError(
                f"the bridge exited with code {process.wait()} before answering; see its stderr"
            )
        try:
            response = json.loads(reply)
        except ValueError:
            raise BridgeError(f"the bridge sent a line that is not JSON: {reply[:200]!r}") from None
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise BridgeError(f"expected a response to request {request_id}, got {reply[:200]!r}")
        error = response.get("error")
        if error is not None:
            if not isinstance(error, dict):
                raise BridgeError(f"malformed error in response: {error!r}")
            raise EvaluationError(str(error.get("type")), str(error.get("message")))
        return response

    @staticmethod
    def _pipes(process: subprocess.Popen[bytes]) -> tuple[IO[bytes], IO[bytes]]:
        if process.stdin is None or process.stdout is None:
            raise BridgeError("the bridge process has no pipes")
        return process.stdin, process.stdout

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        response = self._request("per_plan", query=to_bridge_row(record), plan=plan)
        result = parse_per_plan(record.query_id, response)
        if result.delivered != bool(plan):
            raise BridgeError(f"{record.query_id}: delivered is {result.delivered} for this plan")
        return result

    def aggregate(
        self, plans_path: Path, records_path: Path, set_type: str = "validation"
    ) -> Metrics:
        require_validation_split(set_type)
        response = self._request(
            "aggregate",
            set_type=set_type,
            plans_path=str(plans_path.resolve()),
            records_path=str(records_path.resolve()),
        )
        return parse_metrics(response)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


# --- the fake bridge ---------------------------------------------------------------------


def fake_result(
    query_id: str, local_constraint: LocalConstraint, plan: Plan | None
) -> PerPlanResult:
    """``FakeBridge``'s fixed verdict: undelivered for no plan, otherwise everything passes."""
    if not plan:
        return PerPlanResult(query_id=query_id, delivered=False, commonsense=None, hard=None)
    hard: ConstraintGroup = {"valid_cost": (True, None)}
    for key, check in LOCAL_CONSTRAINTS.items():
        hard[check] = (None, None) if local_constraint.get(key) is None else (True, None)
    return PerPlanResult(
        query_id=query_id,
        delivered=True,
        commonsense=dict.fromkeys(COMMONSENSE_KEYS, (True, None)),
        hard={key: hard[key] for key in HARD_KEYS},
    )


@dataclass(frozen=True, slots=True)
class _Query:
    """The fields ``aggregate`` reads, from one bridge row."""

    query_id: str
    level: str
    days: int
    local_constraint: LocalConstraint

    @classmethod
    def from_row(cls, query_id: str, row: Mapping[str, Any]) -> "_Query":
        return cls(
            query_id, row["level"], row["days"], parse_local_constraint(row["local_constraint"])
        )


class FakeBridge:
    """A stand-in for ``RealBridge`` with no subprocess, database or evaluator."""

    def __init__(self, results: Mapping[str, PerPlanResult] | None = None) -> None:
        self._results = dict(results or {})

    def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
        if record.query_id in self._results:
            return self._results[record.query_id]
        return fake_result(record.query_id, record.local_constraint, plan)

    def aggregate(
        self, plans_path: Path, records_path: Path, set_type: str = "validation"
    ) -> Metrics:
        require_validation_split(set_type)
        rows = read_bridge_records(records_path)
        plans = read_plans(plans_path)
        if len(plans) < len(rows):
            raise ValueError(f"{plans_path.name} has {len(plans)} plans for {len(rows)} queries")
        queries = [_Query.from_row(query_id_for(i), row) for i, row in enumerate(rows, start=1)]
        results = [
            self._results.get(q.query_id) or fake_result(q.query_id, q.local_constraint, plan)
            for q, plan in zip(queries, plans, strict=False)
        ]
        return aggregate(results, queries)

    def close(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def bridge_from_env() -> EvaluatorBridge:
    """``FakeBridge`` if ``TRIPARTITE_EVAL_BRIDGE=fake``, ``RealBridge`` if unset or ``real``."""
    value = os.environ.get(BRIDGE_ENV, "real")
    if value == "fake":
        return FakeBridge()
    if value == "real":
        return RealBridge()
    raise ValueError(f"{BRIDGE_ENV} must be 'real' or 'fake', got {value!r}")
