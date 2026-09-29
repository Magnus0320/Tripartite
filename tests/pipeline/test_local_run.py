"""One real single-pair run, end to end (local; ARCHITECTURE.md D1 local gate, D4, D5, D7).

Needs ``make setup``, ``make data``, ``make pull-model``, the committed calibration and the
dedicated server (``make serve-model``). Run with ``make test-local``; never in CI.

It runs ``configs/single.yaml`` (``val-001``, seed 0) with the real model, the real tokenizer and
the real evaluator bridge. It takes the real ``runs/.model.lock`` (one model caller at a time,
system-wide, D4) and scans the real ``runs/ollama-server.log`` from its own offset; only the run
directory goes under ``tmp_path``. The run must succeed, write every D7 file, pass every
post-check and the truncation scan, and re-score byte for byte (R1).
"""

from pathlib import Path

import pytest

from tripartite.config import MODEL_LOCK_PATH, SERVER_LOG_PATH, SINGLE_CONFIG_PATH
from tripartite.llm.calibration import CALIBRATION_REPORT_PATH
from tripartite.pipeline.run import RunDeps, rescore_run, start_run
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import LlmCallEvent, Metrics, RunManifest

pytestmark = pytest.mark.local


def test_a_real_single_run_succeeds_and_rescores_byte_identical(tmp_path: Path) -> None:
    deps = RunDeps(
        runs_dir=tmp_path / "runs",
        lock_path=MODEL_LOCK_PATH,
        calibration_path=CALIBRATION_REPORT_PATH,
        server_log_path=SERVER_LOG_PATH,
    )

    outcome = start_run(SINGLE_CONFIG_PATH, deps)

    assert outcome.status == "succeeded", outcome.error
    names = {p.name for p in outcome.run_dir.iterdir()}
    assert names == {
        "manifest.json",
        "events.jsonl",
        "blobs",
        "plans_seed0.jsonl",
        "per_plan_eval_seed0.jsonl",
        "metrics_seed0.json",
        "metrics.json",
    }
    manifest = RunManifest.model_validate_json((outcome.run_dir / "manifest.json").read_bytes())
    assert manifest.status == "succeeded"
    assert manifest.run_start.model.runtime == "ollama"
    metrics = Metrics.model_validate_json((outcome.run_dir / "metrics.json").read_bytes())
    assert metrics.subset is True
    assert metrics.post_check_mode == "total"
    log = read_events(outcome.run_dir / "events.jsonl")
    calls = [e for e in log if isinstance(e, LlmCallEvent)]
    assert [c.role for c in calls] == ["warmup", "planner"]
    for call in calls:
        assert call.model_extra is not None
        assert call.model_extra["post_check"]["ok"] is True
        assert call.tokens.input_reported == call.tokens.input  # mode total (A-033)

    report = rescore_run(outcome.run_id, runs_dir=deps.runs_dir)

    assert report.ok, report.mismatches
