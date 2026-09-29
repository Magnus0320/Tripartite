"""D3 test 3, ``test_canary_no_leak`` (model, M4; ARCHITECTURE.md D3, FU-16).

The shared synthetic set puts a canary in every evaluator-only field of every row except ``days``:
``CANARY_`` strings in ``org``, ``dest``, ``level``, ``date``, ``local_constraint`` and the CSV's
own ``reference_information`` column, and unique numbers of at least eight digits in
``budget``, ``visiting_city_number`` and ``people_number``. This test runs the full pipeline,
``pipeline.run_one`` for every one of the 180 rows, with the fake LLM client, which records every
request body byte for byte, and asserts that no canary reaches any request.

The ``EvalRecord``s holding the canaries are loaded by the pipeline itself and go to the evaluator
bridge, so the test proves the pipeline keeps them there. ``days`` is covered structurally by D3
tests 1 and 2 (the planner input has no ``days`` field; the prompt is a pure function of ``query``
and ``reference_information``).
"""

import json
from pathlib import Path

from tests.fixtures.model.run_deps import fake_deps, write_config
from tests.fixtures.synthetic_data import N, canaries, query, ref_line
from tripartite.config import load_run_config
from tripartite.evaluation.records import load_eval_records
from tripartite.llm.fake_client import FakeClient, FakeTokenizer
from tripartite.pipeline.run import close_run, open_run, run_one, warm_up


def test_canary_no_leak(tmp_path: Path) -> None:
    client = FakeClient(FakeTokenizer())
    config = load_run_config(write_config(tmp_path / "all.yaml", queries="all", seeds=[0]))
    session = open_run(config, fake_deps(tmp_path, client=client))
    try:
        warm_up(session)
        for i in range(1, N + 1):
            run_one(session, f"val-{i:03d}", 0)
    finally:
        close_run(session)

    bodies = client.requests
    assert len(bodies) == 1 + N  # the warm-up, then one call per row
    tokens = sorted({token for i in range(1, N + 1) for token in canaries(i)})
    assert "CANARY_" in tokens
    assert any(token.isdigit() and len(token) >= 8 for token in tokens)
    leaks = [
        (index, token)
        for index, body in enumerate(bodies)
        for token in tokens
        if token.encode("utf-8") in body
    ]
    assert leaks == []

    # Positive control: the pipeline did load the canaries, and the two allowed fields did
    # reach the requests, so the absence above is not vacuous.
    records = load_eval_records()
    assert all(record.org.startswith("CANARY_") for record in records)
    prompts = [json.loads(body)["prompt"] for body in bodies[1:]]
    for i, prompt in enumerate(prompts, start=1):
        assert query(i) in prompt
        assert ref_line(i) in prompt
