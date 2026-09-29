"""The ``retrieval`` event is reserved and empty in Phase 1 (ARCHITECTURE.md D7, seam S1).

A Phase 1 run emits zero ``retrieval`` events, and the schema still validates one with an empty
payload, so Phase 3 can start writing them without a schema change.
"""

import json
import uuid
from pathlib import Path

import pytest

from tests.fixtures.model.run_deps import fake_deps
from tests.fixtures.model.scored_synthetic import write_scored_synthetic_data_dir
from tripartite.config import SMOKE_CONFIG_PATH
from tripartite.pipeline.run import start_run
from tripartite.runlog.schema import EVENT_ADAPTER, Retrieval, RetrievalEvent


def test_a_phase_1_run_emits_no_retrieval_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A whole run is scored, so it needs the scored copy of the synthetic set (D3 v0.9).
    data = write_scored_synthetic_data_dir(tmp_path / "data")
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(data))

    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path))

    assert outcome.status == "succeeded", outcome.error
    lines = (outcome.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    types = [json.loads(line)["event_type"] for line in lines]
    assert "retrieval" not in types
    assert {"run_start", "llm_call", "parse", "eval", "query_result", "run_end"} == set(types)


def test_the_schema_validates_an_empty_retrieval_payload() -> None:
    payload = Retrieval(call_id="c", agent_id="planner", query_id="val-001", seed=0, payload={})
    event = EVENT_ADAPTER.validate_python(
        {
            "schema_version": 1,
            "event_id": uuid.uuid4(),
            "seq": 0,
            "ts": "2026-09-28T12:00:00Z",
            "run_id": "20260928T120000Z-batch-abababab-1a2b",
            **payload.model_dump(),
        }
    )

    assert isinstance(event, RetrievalEvent)
    assert event.payload == {}
