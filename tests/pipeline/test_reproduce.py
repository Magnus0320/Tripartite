"""``tripartite run reproduce-check`` (ARCHITECTURE.md D1 §Definition of "reproducible", D9 §M5a).

Every run is a fake-mode run on the synthetic data under ``tmp_path``. A second run differs from
the first through a scripted client, or through an edit of its own files under ``tmp_path``.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.fixtures.model.run_deps import (
    PLAN_TEXT,
    TickingClock,
    fake_deps,
    fixed_env,
    write_config,
)
from tripartite import cli as root_cli
from tripartite.config import SMOKE_CONFIG_PATH
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.llm.errors import TransportError
from tripartite.llm.fake_client import FAKE_OUTPUT, FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateRequest, GenerateResult
from tripartite.pipeline import cli
from tripartite.pipeline.reproduce import (
    PreconditionError,
    ReproduceCheck,
    ReproduceReport,
    check_r3,
    reproduce_check,
)
from tripartite.pipeline.resume import resume_run
from tripartite.pipeline.run import RunOutcome, start_run
from tripartite.runlog.schema import Metrics

runner = CliRunner()

SEEDS = (0, 1, 2)
SMOKE_QUERIES = 9
SCORE_FILES = 7
"""What ``rescore_run`` re-writes for three seeds (R1 compares these; R2 covers the plans)."""
NO_PLAN = "I cannot plan this trip."
COMMIT_A, COMMIT_B = "a" * 40, "b" * 40
SPACED_PLAN_LINE = '{"idx":  '
"""A plans line with an extra space: the same plan to the evaluator, other bytes."""


class PairClient:
    """A fake client whose reply depends on the pair's position in run order (seed-major):
    ``replies[i]`` is the text of the i-th pair, or an error raised on every attempt of it."""

    def __init__(self, replies: dict[int, str | Exception]) -> None:
        self.replies = replies
        self.pair = -1
        self.last: tuple[str, int] | None = None
        self.inner = FakeClient(FakeTokenizer(), self.respond)

    def respond(self, _request: GenerateRequest) -> str:
        reply = self.replies.get(self.pair, FAKE_OUTPUT)
        assert isinstance(reply, str)
        return reply

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if "Reply with OK." in request.prompt:
            return FakeClient(FakeTokenizer()).generate(request)
        key = (request.prompt, request.options.seed)
        if key != self.last:
            self.pair += 1
            self.last = key
        reply = self.replies.get(self.pair)
        if isinstance(reply, Exception):
            raise reply
        return self.inner.generate(request)


def make_run(
    tmp_path: Path,
    name: str,
    config: Path = SMOKE_CONFIG_PATH,
    *,
    allow_dirty: bool = False,
    **changes: Any,
) -> RunOutcome:
    """One fake run into the shared ``tmp_path/runs``."""
    runs = tmp_path / "runs"
    deps = fake_deps(tmp_path / name, runs_dir=runs, lock_path=runs / ".model.lock", **changes)
    outcome = start_run(config, deps, allow_dirty=allow_dirty)
    assert outcome.status == "succeeded", outcome.error
    return outcome


@pytest.fixture
def pair(tmp_path: Path) -> tuple[RunOutcome, RunOutcome]:
    """Two smoke runs with the same outputs."""
    return make_run(tmp_path, "a"), make_run(tmp_path, "b")


def check(a: RunOutcome, b: RunOutcome, **kwargs: Any) -> ReproduceReport:
    kwargs.setdefault("git_commit", lambda: COMMIT_A)
    return reproduce_check(
        a.run_id, b.run_id, runs_dir=a.run_dir.parent, clock=TickingClock(), **kwargs
    )


def edit_events(run: RunOutcome, change: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite the run's ``events.jsonl``, passing every event through ``change``."""
    path = run.run_dir / "events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        change(event)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), "utf-8")


def edit_json(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def written(tmp_path: Path) -> list[str]:
    """What a check left behind under ``runs/``: its report folder and any rescore folder."""
    runs = tmp_path / "runs"
    return sorted(
        p.relative_to(runs).as_posix() for p in [*runs.glob("reproduce"), *runs.glob("*/rescore-*")]
    )


# --- all pass ------------------------------------------------------------------------------------


def test_two_identical_runs_pass(pair: tuple[RunOutcome, RunOutcome], tmp_path: Path) -> None:
    a, b = pair

    report = check(a, b)

    assert report.exit_code == 0
    assert report.path == (
        tmp_path / "runs" / "reproduce" / f"{a.run_id}__{b.run_id}" / "reproduce_check.json"
    )
    result = report.check
    assert result.passed
    assert result.r1.passed
    assert result.r2.passed
    assert result.r3.passed
    assert result.tool_git_commit == COMMIT_A
    assert result.preconditions.same_git_commit is True
    assert {k: (v.files_compared, v.mismatched) for k, v in result.r1.per_run.items()} == {
        a.run_id: (SCORE_FILES, []),
        b.run_id: (SCORE_FILES, []),
    }
    for run in (a, b):
        r2 = result.r2.per_run[run.run_id]
        assert (r2.pairs_checked, r2.pairs_skipped_llm_error, r2.mismatched) == (27, 0, [])
        assert len(list(run.run_dir.glob("rescore-*"))) == 1  # the `make eval` path ran
    assert all(m.diff_pp == 0.0 and m.passed for m in result.r3.metrics.values())
    assert result.r3.tolerance_pp == 2.0
    assert result.identity.overall.model_dump() == {"identical": 27, "total": 27, "fraction": 1.0}
    assert {s: (c.identical, c.total) for s, c in result.identity.per_seed.items()} == {
        "0": (9, 9),
        "1": (9, 9),
        "2": (9, 9),
    }
    assert result.identity.first_call == {"0": True, "1": True, "2": True}
    assert result.runs.a.model_dump() == {
        "run_id": a.run_id,
        "git_commit": "0" * 40,
        "config_hash": a.metrics.config_hash if a.metrics else "",
        "allow_dirty": False,
        "resumed": False,
        "subset": True,
        "n_queries": SMOKE_QUERIES,
        "seeds": [0, 1, 2],
    }
    assert result.runs.b.run_id == b.run_id


def test_the_file_has_exactly_the_specified_keys(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair

    report = check(a, b)

    data = json.loads(report.path.read_text(encoding="utf-8"))
    assert ReproduceCheck.model_validate(data) == report.check
    assert report.path.read_text(encoding="utf-8").endswith("}\n")
    assert list(data) == [
        "schema_version",
        "created_at",
        "tool_git_commit",
        "runs",
        "preconditions",
        "r1",
        "r2",
        "r3",
        "identity",
        "warnings",
        "pass",
    ]
    run_ref = [
        "run_id",
        "git_commit",
        "config_hash",
        "allow_dirty",
        "resumed",
        "subset",
        "n_queries",
        "seeds",
    ]
    assert {k: list(v) for k, v in data["runs"].items()} == {"a": run_ref, "b": run_ref}
    assert data["preconditions"] == {
        "same_config_hash": True,
        "same_stack": True,
        "same_prompt": True,
        "same_parser": True,
        "same_mode": True,
        "same_git_commit": True,
    }
    assert list(data["r1"]) == ["pass", "per_run"]
    assert list(data["r1"]["per_run"][a.run_id]) == ["files_compared", "mismatched"]
    assert list(data["r2"]) == ["pass", "per_run"]
    assert list(data["r2"]["per_run"][b.run_id]) == [
        "pairs_checked",
        "pairs_skipped_llm_error",
        "mismatched",
    ]
    assert list(data["r3"]) == ["pass", "tolerance_pp", "metrics"]
    assert list(data["r3"]["metrics"]) == [
        "Delivery Rate",
        "Commonsense Constraint Micro Pass Rate",
        "Commonsense Constraint Macro Pass Rate",
        "Hard Constraint Micro Pass Rate",
        "Hard Constraint Macro Pass Rate",
        "Final Pass Rate",
    ]
    assert all(
        list(m) == ["mean_a", "mean_b", "diff_pp", "pass"] for m in data["r3"]["metrics"].values()
    )
    assert list(data["identity"]) == ["overall", "per_seed", "first_call"]
    assert list(data["identity"]["overall"]) == ["identical", "total", "fraction"]
    assert data["schema_version"] == 1
    assert datetime.fromisoformat(data["created_at"]).tzinfo == UTC


ALLOWED_STRINGS = re.compile(
    r"\d{8}T\d{6}Z-(batch|single)-[0-9a-f]{8}-[0-9a-f]{4}"  # a run id
    r"|[0-9a-f]{40}|[0-9a-f]{64}"  # a commit, a hash
    r"|\d{4}-\d\d-\d\dT[\d:.]+Z"  # a timestamp
    r"|val-\d{3}"
    r"|(per_plan_eval_seed\d+\.jsonl|metrics_seed\d+\.json|metrics\.json)"
)


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def test_the_file_holds_no_plan_output_or_query_text(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a", client=PairClient(dict.fromkeys(range(27), PLAN_TEXT)))
    b = make_run(tmp_path, "b", client=PairClient({0: NO_PLAN, 5: PLAN_TEXT}))
    path = b.run_dir / "plans_seed1.jsonl"  # an R1 and an R2 mismatch, so both lists are filled
    path.write_text(path.read_text("utf-8").replace('{"idx": ', SPACED_PLAN_LINE, 1), "utf-8")
    scores = b.run_dir / "metrics_seed2.json"
    scores.write_text(scores.read_text("utf-8") + " ", "utf-8")

    report = check(a, b, allow_different_commit=True)

    text = report.path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["r1"]["per_run"][b.run_id]["mismatched"] == ["metrics_seed2.json"]
    assert data["r2"]["per_run"][b.run_id]["mismatched"] == [{"query_id": "val-001", "seed": 1}]
    for fragment in ("Synthville", "Day 1", "Current City", NO_PLAN, "CANARY"):
        assert fragment not in text
    for inp in load_planner_inputs():
        assert inp.query not in text
    warnings = data.pop("warnings")
    assert warnings
    assert all(w.startswith(("run 2026", "--allow-different-commit")) for w in warnings)
    assert [s for s in strings(data) if not ALLOWED_STRINGS.fullmatch(s)] == []


# --- R1 ------------------------------------------------------------------------------------------


def test_an_r1_mismatch_fails_and_names_the_file(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair
    path = b.run_dir / "per_plan_eval_seed1.jsonl"
    path.write_text(
        path.read_text("utf-8").replace('"delivered": true', '"delivered": false', 1), "utf-8"
    )

    report = check(a, b)

    assert report.exit_code == 1
    assert report.path.exists()  # still written
    result = report.check
    assert (result.r1.passed, result.r2.passed, result.r3.passed, result.passed) == (
        False,
        True,
        True,
        False,
    )
    assert result.r1.per_run[a.run_id].mismatched == []
    assert result.r1.per_run[b.run_id].mismatched == ["per_plan_eval_seed1.jsonl"]
    assert result.r1.per_run[b.run_id].files_compared == SCORE_FILES


# --- R2 ------------------------------------------------------------------------------------------


def test_an_r2_plan_mismatch_fails_and_names_the_pair(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair
    path = a.run_dir / "plans_seed2.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[3] = lines[3].replace('{"idx": ', SPACED_PLAN_LINE)  # val-061: same plan, other bytes
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = check(a, b)

    assert report.exit_code == 1
    result = report.check
    assert (result.r1.passed, result.r2.passed, result.r3.passed) == (True, False, True)
    assert [m.model_dump() for m in result.r2.per_run[a.run_id].mismatched] == [
        {"query_id": "val-061", "seed": 2}
    ]
    assert result.r2.per_run[a.run_id].pairs_checked == 27
    assert result.r2.per_run[b.run_id].mismatched == []


def test_an_r2_failure_reason_mismatch_fails(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair

    def change(event: dict[str, Any]) -> None:
        if event["event_type"] == "query_result" and (event["query_id"], event["seed"]) == (
            "val-021",
            1,
        ):
            event["failure_reason"] = "no_fields"  # the output parses, so the parser says None

    edit_events(b, change)

    report = check(a, b)

    assert report.exit_code == 1
    assert (report.check.r1.passed, report.check.r2.passed) == (True, False)
    assert [m.model_dump() for m in report.check.r2.per_run[b.run_id].mismatched] == [
        {"query_id": "val-021", "seed": 1}
    ]


def test_r2_re_parses_unparsable_and_cut_outputs_to_the_stored_reason(tmp_path: Path) -> None:
    """``no_day_blocks`` is the parser's reason; ``length_no_plan`` needs the call's done_reason."""
    config = write_config(tmp_path / "short.yaml", num_predict=3)
    replies: dict[int, str | Exception] = {1: NO_PLAN}
    a = make_run(tmp_path, "a", config, client=PairClient(replies))
    b = make_run(tmp_path, "b", config, client=PairClient(replies))
    assert a.metrics is not None
    assert a.metrics.non_delivery["length_no_plan"] > 0

    report = check(a, b)

    assert report.check.r2.passed
    assert report.check.r2.per_run[a.run_id].pairs_checked == 27


def test_r2_skips_and_counts_llm_error_pairs(tmp_path: Path) -> None:
    failing: dict[int, str | Exception] = {9: TransportError("connection refused")}
    a = make_run(tmp_path, "a", client=PairClient(failing))  # val-001 at seed 1: llm_error
    b = make_run(tmp_path, "b")

    report = check(a, b)

    result = report.check
    assert result.r2.passed
    r2 = result.r2.per_run[a.run_id]
    assert (r2.pairs_checked, r2.pairs_skipped_llm_error) == (26, 1)
    assert result.r2.per_run[b.run_id].pairs_skipped_llm_error == 0
    # no output in run a, so the pair is outside the identity counts, and as a first call: false
    assert (result.identity.overall.identical, result.identity.overall.total) == (26, 26)
    assert result.identity.per_seed["1"].total == 8
    assert result.identity.first_call == {"0": True, "1": False, "2": True}


# --- R3 ------------------------------------------------------------------------------------------


def with_means(metrics: Metrics, mean: float) -> Metrics:
    data = metrics.model_dump(mode="json")
    for summary in data["metrics"].values():
        summary["mean"] = mean
    return Metrics.model_validate(data)


@pytest.mark.parametrize(
    ("mean_b", "passes"),
    [(0.52, True), (0.48, True), (0.5201, False), (0.4799, False), (0.5, True)],
    ids=["+2.0pp", "-2.0pp", "+2.01pp", "-2.01pp", "equal"],
)
def test_r3_passes_at_exactly_2_pp_and_fails_at_2_01(
    mean_b: float, passes: bool, pair: tuple[RunOutcome, RunOutcome]
) -> None:
    assert pair[0].metrics is not None

    r3 = check_r3(with_means(pair[0].metrics, 0.5), with_means(pair[0].metrics, mean_b))

    assert r3.passed is passes
    assert len(r3.metrics) == 6
    for metric in r3.metrics.values():
        assert (metric.mean_a, metric.mean_b, metric.passed) == (0.5, mean_b, passes)
        assert metric.diff_pp == pytest.approx(abs(0.5 - mean_b) * 100, abs=1e-12)


def test_r3_fails_if_one_metric_is_outside(pair: tuple[RunOutcome, RunOutcome]) -> None:
    assert pair[0].metrics is not None
    data = pair[0].metrics.model_dump(mode="json")
    mean = data["metrics"]["Final Pass Rate"]["mean"]
    data["metrics"]["Final Pass Rate"]["mean"] = mean - 0.03 if mean >= 0.03 else mean + 0.03

    r3 = check_r3(pair[0].metrics, Metrics.model_validate(data))

    assert not r3.passed
    assert [key for key, m in r3.metrics.items() if not m.passed] == ["Final Pass Rate"]
    assert r3.metrics["Final Pass Rate"].diff_pp == pytest.approx(3.0)


def test_an_r3_failure_end_to_end(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a")
    b = make_run(tmp_path, "b", client=PairClient(dict.fromkeys(range(9), NO_PLAN)))  # seed 0

    report = check(a, b)

    assert report.exit_code == 1
    result = report.check
    assert (result.r1.passed, result.r2.passed, result.r3.passed, result.passed) == (
        True,
        True,
        False,
        False,
    )
    delivery = result.r3.metrics["Delivery Rate"]
    assert (delivery.mean_a, delivery.passed) == (1.0, False)
    assert delivery.diff_pp == pytest.approx(100 / 3)
    assert (result.identity.overall.identical, result.identity.overall.total) == (18, 27)
    assert result.identity.per_seed["0"].model_dump() == {
        "identical": 0,
        "total": 9,
        "fraction": 0.0,
    }


# --- the identity diagnostic ---------------------------------------------------------------------


def test_identity_counts_per_seed_and_for_first_calls(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a")
    # seed-major: pairs 9..17 are seed 1, and pair 9 is its first call (val-001)
    b = make_run(tmp_path, "b", client=PairClient({9: PLAN_TEXT, 11: PLAN_TEXT, 26: PLAN_TEXT}))

    identity = check(a, b).check.identity

    assert identity.overall.model_dump() == {"identical": 24, "total": 27, "fraction": 24 / 27}
    assert {seed: c.model_dump() for seed, c in identity.per_seed.items()} == {
        "0": {"identical": 9, "total": 9, "fraction": 1.0},
        "1": {"identical": 7, "total": 9, "fraction": 7 / 9},
        "2": {"identical": 8, "total": 9, "fraction": 8 / 9},
    }
    assert identity.first_call == {"0": True, "1": False, "2": True}


# --- preconditions: exit 2, nothing written ------------------------------------------------------


def on_run_start(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def apply(event: dict[str, Any]) -> None:
        if event["event_type"] == "run_start":
            change(event)

    return apply


def on_llm_call(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def apply(event: dict[str, Any]) -> None:
        if event["event_type"] == "llm_call":
            change(event)

    return apply


def set_in(*keys: str, value: object) -> Callable[[dict[str, Any]], None]:
    def change(event: dict[str, Any]) -> None:
        target = event
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value

    return change


EVENT_EDITS: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "config_hash": (on_run_start(set_in("config_hash", value="f" * 64)), "config_hash differs"),
    "ollama_version": (
        on_run_start(set_in("model", "runtime_version", value="0.0.1")),
        "the stack differs: model.runtime_version",
    ),
    "model_digest": (
        on_run_start(set_in("model", "digest", value="sha256:" + "f" * 64)),
        "the stack differs: model.digest",
    ),
    "tokenizer_revision": (
        on_run_start(set_in("model", "tokenizer_revision", value="v2")),
        "the stack differs: model.tokenizer_revision",
    ),
    "runtime_env": (
        on_run_start(set_in("env", "ollama_env", "LLAMA_ARG_CACHE_RAM", value="8192")),
        "the stack differs: runtime.env",
    ),
    "num_ctx": (
        on_llm_call(set_in("request", "num_ctx", value=16384)),
        "the stack differs: num_ctx 32768 vs 16384",
    ),
    "prompt_sha256": (
        on_run_start(set_in("prompt_sha256", value="f" * 64)),
        "prompt sha256 differs",
    ),
    "parser_version": (
        on_run_start(set_in("parser_version", value="rule-text/v0")),
        "parser version differs: rule-text/v1 vs rule-text/v0",
    ),
    "mode": (
        on_llm_call(set_in("post_check", "mode", value="delta")),
        "calibrated mode differs: total vs delta",
    ),
    "git_commit": (
        on_run_start(set_in("env", "git_commit", value=COMMIT_B)),
        "git_commit differs",
    ),
}


@pytest.mark.parametrize("name", EVENT_EDITS)
def test_an_unequal_pin_is_refused_and_nothing_is_written(
    name: str, pair: tuple[RunOutcome, RunOutcome], tmp_path: Path
) -> None:
    a, b = pair
    change, message = EVENT_EDITS[name]
    edit_events(b, change)

    with pytest.raises(PreconditionError, match=re.escape(message)) as raised:
        check(a, b)

    assert len(raised.value.problems) == 1  # only the pin that differs is named
    assert written(tmp_path) == []


def test_a_run_that_did_not_succeed_is_refused(
    pair: tuple[RunOutcome, RunOutcome], tmp_path: Path
) -> None:
    a, b = pair
    edit_json(b.run_dir / "manifest.json", set_in("status", value="failed"))

    with pytest.raises(PreconditionError, match=f"run {b.run_id} is failed"):
        check(a, b)
    with pytest.raises(PreconditionError, match=f"run {b.run_id} is failed"):
        check(b, a)
    assert written(tmp_path) == []


@pytest.mark.parametrize(
    ("run_id", "message"),
    [("20260928T120000Z-batch-00000000-0000", "no run 2026"), ("../a", "is not a run id")],
    ids=["missing", "malformed"],
)
def test_an_unknown_run_is_refused(
    run_id: str, message: str, pair: tuple[RunOutcome, RunOutcome], tmp_path: Path
) -> None:
    runs = tmp_path / "runs"

    with pytest.raises(PreconditionError, match=message):
        reproduce_check(pair[0].run_id, run_id, runs_dir=runs)
    with pytest.raises(PreconditionError, match=message):
        reproduce_check(run_id, pair[0].run_id, runs_dir=runs)
    assert written(tmp_path) == []


def test_the_same_run_twice_is_refused(pair: tuple[RunOutcome, RunOutcome], tmp_path: Path) -> None:
    with pytest.raises(PreconditionError, match="name the same run"):
        check(pair[0], pair[0])
    assert written(tmp_path) == []


def test_runs_of_different_configs_are_refused(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a")
    b = make_run(tmp_path, "b", write_config(tmp_path / "two.yaml", seeds=[0, 1]))

    with pytest.raises(PreconditionError, match="config_hash differs"):
        check(a, b)
    assert written(tmp_path) == []


def test_a_plans_file_without_one_line_per_query_is_refused(
    pair: tuple[RunOutcome, RunOutcome], tmp_path: Path
) -> None:
    a, b = pair
    path = b.run_dir / "plans_seed0.jsonl"
    path.write_text(path.read_text("utf-8") + "{}\n", "utf-8")

    with pytest.raises(PreconditionError, match=r"plans_seed0\.jsonl does not hold one line"):
        check(a, b)
    assert written(tmp_path) == []


def test_changed_dataset_files_are_refused_before_anything_is_written(
    pair: tuple[RunOutcome, RunOutcome], tmp_path: Path
) -> None:
    def change(event: dict[str, Any]) -> None:
        event["dataset"]["files_sha256"] = dict.fromkeys(event["dataset"]["files_sha256"], "0" * 64)

    for run in pair:
        edit_events(run, on_run_start(change))

    with pytest.raises(PreconditionError, match="dataset files differ"):
        check(*pair)
    assert written(tmp_path) == []


# --- warnings and --allow-different-commit -------------------------------------------------------


def test_different_commits_compare_only_with_the_flag(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a", env_probe=partial(fixed_env, git_commit=COMMIT_A))
    b = make_run(tmp_path, "b", env_probe=partial(fixed_env, git_commit=COMMIT_B))

    with pytest.raises(PreconditionError, match=f"git_commit differs: {COMMIT_A} vs {COMMIT_B}"):
        check(a, b)
    report = check(a, b, allow_different_commit=True)

    assert report.exit_code == 0  # a warning never changes the exit code
    assert report.check.preconditions.same_git_commit is False
    assert (report.check.runs.a.git_commit, report.check.runs.b.git_commit) == (COMMIT_A, COMMIT_B)
    assert (
        f"--allow-different-commit was used ({COMMIT_A} vs {COMMIT_B}): diagnostics only, "
        "never the Phase 1 exit"
    ) in report.check.warnings


def test_the_flag_warns_even_when_the_commits_are_equal(
    pair: tuple[RunOutcome, RunOutcome],
) -> None:
    report = check(*pair, allow_different_commit=True)

    assert report.check.preconditions.same_git_commit is True
    assert any(w.startswith("--allow-different-commit was used") for w in report.check.warnings)


def test_a_subset_run_warns(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair

    report = check(a, b)

    assert report.check.warnings == [
        f"run {a.run_id} is a subset run (n_queries 9), not a result",
        f"run {b.run_id} is a subset run (n_queries 9), not a result",
    ]


def test_two_clean_full_runs_have_no_warnings(tmp_path: Path) -> None:
    config = write_config(tmp_path / "full.yaml", queries="all", seeds=[0])
    a, b = make_run(tmp_path, "a", config), make_run(tmp_path, "b", config)

    report = check(a, b)

    assert report.exit_code == 0
    assert report.check.warnings == []
    assert (report.check.runs.a.subset, report.check.runs.a.n_queries) == (False, 180)
    assert report.check.identity.overall.total == 180
    assert report.check.identity.first_call == {"0": True}
    assert report.check.r1.per_run[a.run_id].files_compared == 3  # one seed


def test_allow_dirty_warns(tmp_path: Path) -> None:
    a = make_run(tmp_path, "a", allow_dirty=True)
    b = make_run(tmp_path, "b")

    report = check(a, b)

    assert (report.check.runs.a.allow_dirty, report.check.runs.b.allow_dirty) == (True, False)
    assert f"run {a.run_id} has allow_dirty: true in a run_start" in report.check.warnings
    assert not any(b.run_id in w and "allow_dirty" in w for w in report.check.warnings)


class Interrupting:
    """Ctrl-C on the ``stop_at``-th planner call."""

    def __init__(self, stop_at: int) -> None:
        self.inner = FakeClient(FakeTokenizer())
        self.stop_at = stop_at
        self.calls = 0

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if "Reply with OK." not in request.prompt:
            self.calls += 1
            if self.calls == self.stop_at:
                raise KeyboardInterrupt
        return self.inner.generate(request)


def test_a_resumed_run_warns_with_its_sessions(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    a = make_run(tmp_path, "a")
    stopped = start_run(
        SMOKE_CONFIG_PATH, fake_deps(tmp_path / "b", runs_dir=runs, client=Interrupting(4))
    )
    assert stopped.status == "interrupted"
    b = resume_run(stopped.run_id, fake_deps(tmp_path / "c", runs_dir=runs))
    assert b.status == "succeeded", b.error

    report = check(a, b)

    assert report.exit_code == 0
    assert (report.check.runs.a.resumed, report.check.runs.b.resumed) == (False, True)
    assert f"run {b.run_id} was resumed (2 sessions)" in report.check.warnings
    assert report.check.identity.overall.identical == 27


def test_a_repaired_tail_warns(pair: tuple[RunOutcome, RunOutcome]) -> None:
    a, b = pair
    edit_json(b.run_dir / "manifest.json", set_in("repaired_tail_bytes", value=17))

    report = check(a, b)

    assert f"run {b.run_id} has repaired_tail_bytes 17" in report.check.warnings


# --- the CLI -------------------------------------------------------------------------------------


@pytest.fixture
def cli_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Two smoke runs started through the CLI, which is pointed at ``tmp_path``."""
    monkeypatch.setattr(cli, "default_deps", lambda: fake_deps(tmp_path))
    monkeypatch.setattr(cli.signal, "signal", lambda *_args: None)
    ids = []
    for _ in range(2):
        started = runner.invoke(cli.app, ["start", "--config", str(SMOKE_CONFIG_PATH)])
        assert started.exit_code == 0, started.output
        ids.append(started.output.splitlines()[0].split()[3])
    return ids[0], ids[1]


def invoke(app: Any, *args: str) -> Any:
    return runner.invoke(app, ["reproduce-check", *args])


def test_the_cli_prints_the_checks_and_exits_0(cli_runs: tuple[str, str], tmp_path: Path) -> None:
    a, b = cli_runs

    result = invoke(cli.app, "--run", a, "--run2", b)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert all(line.startswith("run reproduce-check: ") for line in lines)
    body = [line.removeprefix("run reproduce-check: ") for line in lines]
    assert body[0] == (
        f"R1 PASS (re-scoring): {a}: 7 files compared, all byte-identical; "
        f"{b}: 7 files compared, all byte-identical"
    )
    assert body[1] == (
        f"R2 PASS (re-parsing): {a}: 27 pairs checked, 0 skipped (llm_error), 0 mismatched; "
        f"{b}: 27 pairs checked, 0 skipped (llm_error), 0 mismatched"
    )
    assert body[2] == ("R3 PASS (regeneration, tolerance 2.0 pp): all six means within tolerance")
    assert body[3].split() == ["metric", "mean_a", "mean_b", "diff_pp"]
    assert body[4].split() == ["Delivery", "Rate", "1.000000", "1.000000", "0.0000", "PASS"]
    assert [line.rsplit(None, 4)[0].strip() for line in body[4:10]] == [
        "Delivery Rate",
        "Commonsense Constraint Micro Pass Rate",
        "Commonsense Constraint Macro Pass Rate",
        "Hard Constraint Micro Pass Rate",
        "Hard Constraint Macro Pass Rate",
        "Final Pass Rate",
    ]
    assert body[10:15] == [
        "identity overall: 27/27 (1.0000)",
        "identity seed 0: 9/9 (1.0000)",
        "identity seed 1: 9/9 (1.0000)",
        "identity seed 2: 9/9 (1.0000)",
        "identity first calls: seed 0 identical, seed 1 identical, seed 2 identical",
    ]
    assert body[15:17] == [
        f"WARNING: run {a} is a subset run (n_queries 9), not a result",
        f"WARNING: run {b} is a subset run (n_queries 9), not a result",
    ]
    path = tmp_path / "runs" / "reproduce" / f"{a}__{b}" / "reproduce_check.json"
    assert body[17:] == [f"PASS: wrote {path}"]
    assert json.loads(path.read_text(encoding="utf-8"))["pass"] is True


def test_the_root_cli_reaches_reproduce_check(cli_runs: tuple[str, str]) -> None:
    a, b = cli_runs

    result = runner.invoke(
        root_cli.app,
        ["run", "reproduce-check", "--run", a, "--run2", b, "--allow-different-commit"],
    )

    assert result.exit_code == 0, result.output
    assert "WARNING: --allow-different-commit was used" in result.output


def test_a_failed_check_exits_1_and_still_writes(cli_runs: tuple[str, str], tmp_path: Path) -> None:
    a, b = cli_runs
    metrics = tmp_path / "runs" / b / "metrics.json"
    metrics.write_text(metrics.read_text(encoding="utf-8") + " ", encoding="utf-8")

    result = invoke(cli.app, "--run", a, "--run2", b)

    assert result.exit_code == 1, result.output
    assert f"{b}: 7 files compared, mismatched ['metrics.json']" in result.output
    assert "run reproduce-check: R1 FAIL" in result.output
    assert "run reproduce-check: R2 PASS" in result.output
    path = tmp_path / "runs" / "reproduce" / f"{a}__{b}" / "reproduce_check.json"
    assert result.output.splitlines()[-1] == f"run reproduce-check: FAIL: wrote {path}"
    assert json.loads(path.read_text(encoding="utf-8"))["pass"] is False


@pytest.mark.parametrize("other", ["20260928T120000Z-batch-00000000-0000", "not-a-run-id"])
def test_runs_that_cannot_be_compared_exit_2(
    other: str, cli_runs: tuple[str, str], tmp_path: Path
) -> None:
    result = invoke(cli.app, "--run", cli_runs[0], "--run2", other)

    assert result.exit_code == 2, result.output
    assert result.output.splitlines()[-1] == "run reproduce-check: CANNOT COMPARE, nothing written"
    assert written(tmp_path) == []


def test_an_unequal_pin_exits_2_from_the_cli(cli_runs: tuple[str, str], tmp_path: Path) -> None:
    a, b = cli_runs
    path = tmp_path / "runs" / b / "events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    events[0]["env"]["git_commit"] = COMMIT_B
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), "utf-8")

    result = invoke(cli.app, "--run", a, "--run2", b)

    assert result.exit_code == 2, result.output
    assert "run reproduce-check: git_commit differs" in result.output
    assert written(tmp_path) == []
