"""``reproduce-check`` on two real single-pair runs (local; ARCHITECTURE.md D1 local gate, D9 §M5a).

Needs what ``test_local_run`` needs: ``make setup``, ``make data``, ``make pull-model``, the
committed calibration and the dedicated server (``make serve-model``). Run with
``make test-local``; never in CI.

It runs ``configs/single.yaml`` (``val-001``, seed 0) twice, one run after the other, with the
real model, tokenizer and evaluator bridge, under the real ``runs/.model.lock`` and server log;
the run directories and the report go under ``tmp_path``. Both runs record this tree's commit, so
``--allow-different-commit`` is not needed. R1 and R2 are exact and must pass. Whether the two
outputs are byte-identical, and so whether R3 passes on one query, is a measurement (A-051), not
something this test may assert.
"""

from pathlib import Path

import pytest

from tripartite.config import MODEL_LOCK_PATH, SERVER_LOG_PATH, SINGLE_CONFIG_PATH
from tripartite.llm.calibration import CALIBRATION_REPORT_PATH
from tripartite.pipeline.reproduce import ReproduceCheck, reproduce_check
from tripartite.pipeline.run import RunDeps, start_run

pytestmark = pytest.mark.local


def test_reproduce_check_on_two_real_single_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_ids = []
    for _ in range(2):
        deps = RunDeps(
            runs_dir=runs,
            lock_path=MODEL_LOCK_PATH,
            calibration_path=CALIBRATION_REPORT_PATH,
            server_log_path=SERVER_LOG_PATH,
        )
        outcome = start_run(SINGLE_CONFIG_PATH, deps)
        assert outcome.status == "succeeded", outcome.error
        run_ids.append(outcome.run_id)
    a, b = run_ids

    report = reproduce_check(a, b, runs_dir=runs)

    assert report.path == runs / "reproduce" / f"{a}__{b}" / "reproduce_check.json"
    check = ReproduceCheck.model_validate_json(report.path.read_bytes())
    assert check == report.check
    assert check.preconditions.same_git_commit is True
    assert check.r1.passed, check.r1.per_run
    assert {r.files_compared for r in check.r1.per_run.values()} == {3}
    assert check.r2.passed, check.r2.per_run
    assert {(r.pairs_checked, r.pairs_skipped_llm_error) for r in check.r2.per_run.values()} == {
        (1, 0)
    }
    assert check.identity.overall.total == 1
    assert check.identity.per_seed["0"].total == 1
    assert check.identity.first_call == {"0": check.identity.overall.identical == 1}
    assert check.passed is check.r3.passed
    assert report.exit_code == (0 if check.r3.passed else 1)
    assert check.warnings == [
        f"run {a} is a subset run (n_queries 1), not a result",
        f"run {b} is a subset run (n_queries 1), not a result",
    ]
