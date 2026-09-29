"""``tripartite run rescore`` (ARCHITECTURE.md D1 Phase 0 exit item 5, R1).

It reads a finished run's stored ``plans_seed*.jsonl``, never re-generates or re-parses, writes
into ``runs/<run_id>/rescore-<UTC ts>/`` with the code that scored the run, and compares every
re-written file byte for byte.
"""

import json
from pathlib import Path

import pytest

from tests.fixtures.model.run_deps import TickingClock, fake_deps, write_config
from tripartite.config import SMOKE_CONFIG_PATH
from tripartite.data.manifest import raw_dir
from tripartite.evaluation.bridge_client import EvaluationError, FakeBridge, Plan
from tripartite.evaluation.constraints import PerPlanResult
from tripartite.evaluation.records import EvalRecord
from tripartite.pipeline import run as run_module
from tripartite.pipeline.run import RescoreError, RunOutcome, rescore_run, start_run

SCORE_FILES = [
    *(f"{name}{s}.{ext}" for s in (0, 1, 2) for name, ext in (
        ("per_plan_eval_seed", "jsonl"),
        ("metrics_seed", "json"),
    )),
    "metrics.json",
]  # fmt: skip


@pytest.fixture
def smoke(tmp_path: Path) -> RunOutcome:
    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path))
    assert outcome.status == "succeeded", outcome.error
    return outcome


def rescore(outcome: RunOutcome, **kwargs: object) -> run_module.RescoreReport:
    return rescore_run(
        outcome.run_id,
        runs_dir=outcome.run_dir.parent,
        clock=TickingClock(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_rescore_is_byte_identical(smoke: RunOutcome) -> None:
    report = rescore(smoke)

    assert report.ok, report.mismatches
    assert report.compared == SCORE_FILES
    assert report.out_dir.parent == smoke.run_dir
    assert report.out_dir.name.startswith("rescore-")
    assert sorted(p.name for p in report.out_dir.iterdir()) == sorted(SCORE_FILES)
    for name in SCORE_FILES:
        assert (report.out_dir / name).read_bytes() == (smoke.run_dir / name).read_bytes()


def test_a_full_run_rescores_through_the_bridge_aggregate(tmp_path: Path) -> None:
    config = write_config(tmp_path / "full.yaml", queries="all", seeds=[0])
    outcome = start_run(config, fake_deps(tmp_path))

    report = rescore(outcome)

    assert report.ok, report.mismatches
    assert json.loads((report.out_dir / "metrics_seed0.json").read_text())["source"] == (
        "official_eval_score"
    )


def test_a_difference_is_named_and_fails(smoke: RunOutcome) -> None:
    path = smoke.run_dir / "per_plan_eval_seed1.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"delivered": true', '"delivered": false')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = rescore(smoke)

    assert not report.ok
    assert report.mismatches == ["per_plan_eval_seed1.jsonl: line 3 differs"]


def test_the_rescore_reads_the_stored_plans(smoke: RunOutcome) -> None:
    path = smoke.run_dir / "plans_seed0.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["plan"] = None
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")

    report = rescore(smoke)

    assert [m.split(":")[0] for m in report.mismatches] == [
        "per_plan_eval_seed0.jsonl",
        "metrics_seed0.json",
        "metrics.json",
    ]


def test_the_rescore_never_builds_a_model_client(
    smoke: RunOutcome, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rescore built a model client")

    monkeypatch.delenv("TRIPARTITE_LLM")
    monkeypatch.setattr(run_module, "make_client", refuse)
    monkeypatch.setattr(run_module, "OllamaClient", refuse)
    monkeypatch.setattr(run_module, "acquire_model_lock", refuse)

    assert rescore(smoke).ok


def test_the_rescore_evaluates_every_stored_plan_again(smoke: RunOutcome) -> None:
    seen: list[str] = []

    class Counting(FakeBridge):
        def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
            seen.append(record.query_id)
            return super().per_plan(record, plan)

    assert rescore(smoke, bridge=Counting()).ok
    assert len(seen) == 27


def test_an_evaluator_crash_during_a_rescore_raises(smoke: RunOutcome) -> None:
    class Crashing(FakeBridge):
        def per_plan(self, record: EvalRecord, plan: Plan | None) -> PerPlanResult:
            raise EvaluationError("KeyError", "'days'")

    with pytest.raises(EvaluationError):
        rescore(smoke, bridge=Crashing())


def test_only_a_succeeded_run_is_rescored(tmp_path: Path) -> None:
    config = write_config(tmp_path / "c.yaml", queries=["val-001"], seeds=[0], num_predict=32000)
    failed = start_run(config, fake_deps(tmp_path))

    with pytest.raises(RescoreError, match="is failed"):
        rescore(failed)
    with pytest.raises(RescoreError, match="no run"):
        rescore_run("20260928T120000Z-batch-00000000-0000", runs_dir=tmp_path)


def test_a_rescore_refuses_changed_dataset_files(smoke: RunOutcome) -> None:
    csv = raw_dir() / "validation.csv"
    csv.write_bytes(csv.read_bytes() + b"\n")

    with pytest.raises(RescoreError, match="dataset files differ"):
        rescore(smoke)
