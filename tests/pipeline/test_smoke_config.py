"""``configs/smoke.yaml`` (ARCHITECTURE.md D1 Phase 0 exit item 3).

Its ``query_ids`` are the output of ``tripartite eval smoke-ids``, committed verbatim in M4. The
``local`` test recomputes them from the real EvalRecords; in CI the committed list is checked for
shape, and against ``baseline.yaml``.
"""

import pytest
import yaml

from tripartite.config import BASELINE_CONFIG_PATH, SMOKE_CONFIG_PATH, config_hash, load_run_config
from tripartite.evaluation.cli import smoke_query_ids
from tripartite.evaluation.records import load_eval_records

COMMITTED = [
    "val-001",
    "val-021",
    "val-041",
    "val-061",
    "val-081",
    "val-101",
    "val-121",
    "val-141",
    "val-161",
]


def test_the_smoke_config_is_9_queries_by_3_seeds() -> None:
    config = load_run_config(SMOKE_CONFIG_PATH)

    assert config.queries == COMMITTED
    assert config.seeds == [0, 1, 2]
    assert config.kind == "batch"
    assert config.run.name == "smoke"


def test_the_smoke_config_is_the_baseline_but_for_its_name_and_queries() -> None:
    smoke = yaml.safe_load(SMOKE_CONFIG_PATH.read_text(encoding="utf-8"))
    baseline = yaml.safe_load(BASELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    for data in (smoke, baseline):
        del data["run"]
        del data["queries"]

    assert smoke == baseline
    assert config_hash(load_run_config(SMOKE_CONFIG_PATH).model_dump(mode="json")) != config_hash(
        load_run_config(BASELINE_CONFIG_PATH).model_dump(mode="json")
    )


@pytest.mark.local
def test_the_committed_ids_are_what_smoke_ids_prints() -> None:
    assert smoke_query_ids(load_eval_records()) == COMMITTED
