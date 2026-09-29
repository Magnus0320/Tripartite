"""A run end to end in fake mode: the run directory, the event log and the scores (D7, D4, D5).

Every run writes under ``tmp_path`` (``tests/fixtures/model/run_deps.py``) and reads the scored
copy of the shared synthetic set (``tests/pipeline/conftest.py``).
"""

import itertools
import json
from pathlib import Path

import pytest

from tests.fixtures.model.run_deps import PLAN_TEXT, fake_deps, write_config
from tests.fixtures.synthetic_data import query
from tripartite.config import (
    SINGLE_CONFIG_PATH,
    SMOKE_CONFIG_PATH,
    StackConfig,
    config_hash,
    load_run_config,
)
from tripartite.data.manifest import DATABASE_ZIP, HF_REVISION, raw_dir, sha256_file
from tripartite.data.planner_inputs import load_planner_inputs
from tripartite.evaluation.aggregate import OfficialScores, aggregate
from tripartite.evaluation.bridge_client import FakeBridge
from tripartite.evaluation.records import load_eval_records
from tripartite.llm.chat_template import template_from_env
from tripartite.llm.fake_client import FAKE_OUTPUT, FakeClient, FakeTokenizer
from tripartite.llm.ollama_client import GenerateOptions, GenerateRequest, build_generate_body
from tripartite.llm.tokenizer import lcp
from tripartite.parse.text_plan_parser import parse_plan
from tripartite.pipeline.metrics import read_plans_file
from tripartite.pipeline.run import (
    VENDOR_LOCK,
    RunOutcome,
    collect_env,
    resolve_query_ids,
    start_run,
)
from tripartite.planner.prompt import PromptRenderer, load_template
from tripartite.runlog.reader import read_events
from tripartite.runlog.schema import (
    RUN_END_COUNT_KEYS,
    EvalEvent,
    LlmCallEvent,
    Metrics,
    MetricsSeed,
    ParseEvent,
    QueryResultEvent,
    RunEndEvent,
    RunManifest,
    RunStartEvent,
)

SMOKE_IDS = [f"val-{i:03d}" for i in range(1, 162, 20)]
D7_FILES = {
    "manifest.json",
    "events.jsonl",
    "blobs",
    *(f"{name}_seed{s}.{ext}" for s in (0, 1, 2) for name, ext in (("plans", "jsonl"),)),
    *(f"per_plan_eval_seed{s}.jsonl" for s in (0, 1, 2)),
    *(f"metrics_seed{s}.json" for s in (0, 1, 2)),
    "metrics.json",
}


@pytest.fixture
def smoke(tmp_path: Path) -> RunOutcome:
    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path))
    assert outcome.status == "succeeded", outcome.error
    return outcome


def events(outcome: RunOutcome) -> list[object]:
    return list(read_events(outcome.run_dir / "events.jsonl"))


def renderer() -> PromptRenderer:
    config = load_run_config(SMOKE_CONFIG_PATH)
    return PromptRenderer(
        load_template(config.prompt_path, config.prompt.sha256), template_from_env()
    )


# --- the run directory -------------------------------------------------------------------------


def test_a_run_writes_every_d7_file(smoke: RunOutcome) -> None:
    names = {path.name for path in smoke.run_dir.iterdir()}

    assert names == D7_FILES
    assert "reproduce_check.json" not in names  # only reproduce-check writes it (M5)
    manifest = RunManifest.model_validate_json((smoke.run_dir / "manifest.json").read_bytes())
    metrics = Metrics.model_validate_json((smoke.run_dir / "metrics.json").read_bytes())
    for seed in (0, 1, 2):
        seed_metrics = MetricsSeed.model_validate_json(
            (smoke.run_dir / f"metrics_seed{seed}.json").read_bytes()
        )
        assert (seed_metrics.seed, seed_metrics.subset, seed_metrics.n_queries) == (seed, True, 9)
        assert seed_metrics.source == "subset_aggregate"
    assert metrics.subset is True
    assert (metrics.n_queries, metrics.seeds, metrics.kind) == (9, [0, 1, 2], "batch")
    assert metrics == smoke.metrics
    assert (manifest.status, manifest.stage, manifest.metrics_path) == (
        "succeeded",
        "done",
        "metrics.json",
    )
    assert (manifest.progress.done, manifest.progress.total) == (27, 27)
    assert (manifest.created_at, manifest.finished_at) == (metrics.created_at, metrics.finished_at)
    assert (manifest.resumed, manifest.repaired_tail_bytes, manifest.error) == (False, 0, None)


def test_the_event_log(smoke: RunOutcome) -> None:
    log = events(smoke)
    lines = (smoke.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["seq"] for line in lines] == list(range(len(lines)))
    assert isinstance(log[0], RunStartEvent)
    warmup = log[1]
    assert isinstance(warmup, LlmCallEvent)
    assert (warmup.role, warmup.query_id, warmup.seed) == ("warmup", None, None)
    assert warmup.request.num_predict == 1
    body = log[2:-1]
    assert [type(e).__name__ for e in body] == [
        "LlmCallEvent",
        "ParseEvent",
        "EvalEvent",
        "QueryResultEvent",
    ] * 27
    results = [e for e in body if isinstance(e, QueryResultEvent)]
    assert [(r.query_id, r.seed) for r in results] == [
        (q, s) for s in (0, 1, 2) for q in SMOKE_IDS
    ]  # seed-major, query_id order (D4)
    end = log[-1]
    assert isinstance(end, RunEndEvent)
    assert end.status == "succeeded"
    assert end.metrics_path == "metrics.json"
    assert end.counts == {
        "queries": 9,
        "seeds": 3,
        "pairs_total": 27,
        "pairs_done": 27,
        "delivered": 27,
        "llm_calls": 27,
        "errors": 0,
    }
    assert set(RUN_END_COUNT_KEYS) <= set(end.counts)


def test_the_run_start_payload(smoke: RunOutcome, stack: StackConfig) -> None:
    start = events(smoke)[0]
    assert isinstance(start, RunStartEvent)
    config = load_run_config(SMOKE_CONFIG_PATH)

    assert (start.kind, start.mode, start.context_mode, start.split, start.order) == (
        "batch",
        "sole-planning",
        "full",
        "validation",
        "seed-major",
    )
    assert start.query_ids == SMOKE_IDS
    assert start.seeds == [0, 1, 2]
    assert start.config == config.model_dump(mode="json")
    assert start.config_hash == config_hash(start.config)
    assert smoke.run_id.split("-")[2] == start.config_hash[:8]
    model = start.model
    assert (model.runtime, model.tokenizer_repo, model.tokenizer_revision) == (
        "fake",
        "fake-bytes",
        "v1",
    )
    assert (model.tag, model.digest, model.quant) == (
        stack.model.tag,
        stack.model.digest,
        stack.model.quant,
    )
    assert (start.prompt_version, start.prompt_sha256) == ("sp-direct-v1", config.prompt.sha256)
    assert start.parser_version == "rule-text/v1"
    assert start.evaluator.upstream_commit == "e52c87f4ac348a3410c46dc3553c519db5ec5e23"
    assert start.evaluator.vendor_lock_sha256 == sha256_file(VENDOR_LOCK)
    assert start.dataset.revision == HF_REVISION
    assert start.dataset.files_sha256 == {
        name: sha256_file(raw_dir() / name)
        for name in ("validation.csv", "validation_ref_info.jsonl")
    }
    assert start.database_zip_sha256 == DATABASE_ZIP.sha256
    assert [a.model_dump() for a in start.agents] == [
        {"agent_id": "planner", "role": "planner", "model_tag": "qwen3:8b-q4_K_M"}
    ]
    assert start.resumed_from is None


def test_collect_env(stack: StackConfig) -> None:
    env = collect_env(stack)

    assert env.python.startswith("3.12.")
    assert env.ollama_env == stack.runtime.env
    assert len(env.uv_lock_sha256) == 64
    assert env.git_commit == "unknown" or len(env.git_commit) == 40


# --- calls, prompts and blobs --------------------------------------------------------------------


def test_every_call_is_logged_with_its_request_and_counts(smoke: RunOutcome) -> None:
    calls = [e for e in events(smoke) if isinstance(e, LlmCallEvent)]
    tokenizer = FakeTokenizer()

    assert len(calls) == 28
    for call in calls[1:]:
        assert call.request.model_dump() == {
            "endpoint": "/api/generate",
            "num_ctx": 32768,
            "num_predict": 4096,
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "repeat_penalty": 1.0,
            "seed": call.seed,
            "think": False,
            "stop": ["<|im_end|>", "<|endoftext|>"],
        }
        assert (call.agent_id, call.role, call.round, call.parent_call_id) == (
            "planner",
            "planner",
            None,
            None,
        )
        assert call.attempt == 0
        assert call.output_text == FAKE_OUTPUT
        assert call.thinking_text is None
        blob = (smoke.run_dir / "blobs" / f"{call.prompt_sha256}.txt").read_text(encoding="utf-8")
        tokens = call.tokens
        assert tokens.input == tokens.input_reported == tokenizer.count(blob)
        assert tokens.output_visible == tokenizer.count(FAKE_OUTPUT)
        assert tokens.output_thinking == 0
        assert tokens.tokenizer == "fake-bytes@v1"
        assert call.model_extra is not None
        assert call.model_extra["post_check"] == {
            "mode": "total",
            "lcp": call.model_extra["post_check"]["lcp"],
            "expected_min": tokens.input,
            "expected_max": tokens.input,
            "observed": tokens.input,
            "ok": True,
        }


def test_the_first_measured_call_is_checked_against_the_warm_up(smoke: RunOutcome) -> None:
    calls = [e for e in events(smoke) if isinstance(e, LlmCallEvent)]
    tk = FakeTokenizer()

    def ids(call: LlmCallEvent) -> list[int]:
        blob = smoke.run_dir / "blobs" / f"{call.prompt_sha256}.txt"
        return tk.encode_ids(blob.read_text(encoding="utf-8"))

    for previous, call in itertools.pairwise(calls):
        assert call.model_extra is not None
        assert call.model_extra["post_check"]["lcp"] == lcp(ids(previous), ids(call))


def test_blobs_hold_each_rendered_prompt_once(smoke: RunOutcome) -> None:
    calls = [e for e in events(smoke) if isinstance(e, LlmCallEvent)]
    inputs = {inp.query_id: inp for inp in load_planner_inputs()}
    prompts = renderer()

    blobs = sorted(p.name for p in (smoke.run_dir / "blobs").iterdir())
    assert len(blobs) == 10  # nine queries, shared across seeds, and the warm-up
    for call in calls[1:]:
        assert call.query_id is not None
        rendered = prompts.render(inputs[call.query_id])
        assert call.prompt_sha256 == rendered.sha256
        path = smoke.run_dir / "blobs" / f"{rendered.sha256}.txt"
        assert path.read_bytes() == rendered.text.encode("utf-8")


def test_the_fake_client_saw_exactly_the_logged_requests(tmp_path: Path) -> None:
    client = FakeClient(FakeTokenizer())
    outcome = start_run(SMOKE_CONFIG_PATH, fake_deps(tmp_path, client=client))
    calls = [e for e in events(outcome) if isinstance(e, LlmCallEvent)]

    assert len(client.requests) == len(calls) == 28
    for body, call in zip(client.requests, calls, strict=True):
        blob = (outcome.run_dir / "blobs" / f"{call.prompt_sha256}.txt").read_text("utf-8")
        sent = json.loads(body)
        assert sent["prompt"] == blob
        assert sent["options"]["seed"] == call.request.seed
        assert body == build_generate_body(GenerateRequest(sent["model"], blob, _options(call)))


def _options(call: LlmCallEvent) -> GenerateOptions:
    r = call.request
    return GenerateOptions(
        num_ctx=r.num_ctx,
        num_predict=r.num_predict,
        temperature=r.temperature,
        top_p=r.top_p,
        top_k=r.top_k,
        min_p=r.min_p,
        repeat_penalty=r.repeat_penalty,
        seed=r.seed,
        stop=tuple(r.stop),
    )


# --- plans, per-plan results and scores ----------------------------------------------------------


def test_the_plans_files(smoke: RunOutcome) -> None:
    for seed in (0, 1, 2):
        path = smoke.run_dir / f"plans_seed{seed}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert [list(json.loads(line)) for line in lines] == [["idx", "query", "plan"]] * 9
        rows = read_plans_file(path)
        assert [row.query_id for row in rows] == SMOKE_IDS
        assert [row.idx for row in rows] == [int(q[4:]) for q in SMOKE_IDS]
        assert [row.query for row in rows] == [query(row.idx) for row in rows]
        assert all(row.plan == parse_plan(FAKE_OUTPUT).plan for row in rows)


def test_the_per_plan_files_and_the_eval_events(smoke: RunOutcome) -> None:
    evals = [e for e in events(smoke) if isinstance(e, EvalEvent)]
    for seed in (0, 1, 2):
        lines = (smoke.run_dir / f"per_plan_eval_seed{seed}.jsonl").read_text("utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        assert [list(row) for row in rows] == [
            ["idx", "query_id", "delivered", "commonsense", "hard"]
        ] * 9
        by_id = {e.query_id: e for e in evals if e.seed == seed}
        for row in rows:
            event = by_id[row["query_id"]]
            assert row["delivered"] is event.delivered is True
            assert row["commonsense"] == {k: list(v) for k, v in (event.commonsense or {}).items()}
            assert (event.commonsense_pass, event.hard_pass, event.final_pass) == (True,) * 3


def test_subset_scores_are_aggregate_over_the_subset(smoke: RunOutcome) -> None:
    records = {r.query_id: r for r in load_eval_records()}
    bridge = FakeBridge()
    for seed in (0, 1, 2):
        plans = read_plans_file(smoke.run_dir / f"plans_seed{seed}.jsonl")
        expected: OfficialScores = aggregate(
            [bridge.per_plan(records[row.query_id], row.plan) for row in plans],
            [records[row.query_id] for row in plans],
        )
        stored = MetricsSeed.model_validate_json(
            (smoke.run_dir / f"metrics_seed{seed}.json").read_bytes()
        )
        assert stored.scores == expected.scores
        assert stored.detailed == expected.detailed


def test_a_full_run_is_scored_by_the_bridge_aggregate(tmp_path: Path) -> None:
    config = write_config(tmp_path / "full.yaml", queries="all", seeds=[0])

    outcome = start_run(config, fake_deps(tmp_path))

    assert outcome.status == "succeeded", outcome.error
    stored = MetricsSeed.model_validate_json((outcome.run_dir / "metrics_seed0.json").read_bytes())
    assert (stored.source, stored.subset, stored.n_queries) == ("official_eval_score", False, 180)
    assert outcome.metrics is not None
    assert outcome.metrics.subset is False
    assert len((outcome.run_dir / "plans_seed0.jsonl").read_text("utf-8").splitlines()) == 180


class DriftingBridge(FakeBridge):
    """The bridge's official aggregate, off by 1e-9 on one key."""

    def aggregate(
        self, plans_path: Path, records_path: Path, set_type: str = "validation"
    ) -> OfficialScores:
        scores = super().aggregate(plans_path, records_path, set_type)
        drifted = dict(scores.scores)
        drifted["Hard Constraint Micro Pass Rate"] -= 1e-9
        return OfficialScores(scores=drifted, detailed=scores.detailed)


def test_a_full_run_fails_when_aggregate_disagrees_with_the_bridge(tmp_path: Path) -> None:
    config = write_config(tmp_path / "full.yaml", queries="all", seeds=[0])

    outcome = start_run(config, fake_deps(tmp_path, bridge=DriftingBridge()))

    assert outcome.status == "failed"
    assert outcome.error is not None
    assert outcome.error.type == "AggregateMismatchError"
    manifest = RunManifest.model_validate_json((outcome.run_dir / "manifest.json").read_bytes())
    assert manifest.status == "failed"
    assert not (outcome.run_dir / "metrics.json").exists()


# --- non-delivery --------------------------------------------------------------------------------


def respond(request: GenerateRequest) -> str:
    """A different output per synthetic query, each exercising one outcome."""
    if "Reply with OK." in request.prompt:
        return "OK"
    replies = {
        "001": "",
        "002": "I cannot plan this trip.",
        "003": "Day 1:\nA day in Synthville.",
        "004": "Day 1:\n" + "x" * 10_000,
        "005": PLAN_TEXT,
    }
    for number, reply in replies.items():
        if f"Synthetic query {number}" in request.prompt:
            return reply
    raise AssertionError("unexpected query")


def test_each_non_delivery_reason_is_counted(tmp_path: Path) -> None:
    config = write_config(
        tmp_path / "c.yaml", queries=[f"val-00{i}" for i in range(1, 6)], seeds=[0], num_predict=512
    )

    outcome = start_run(
        config, fake_deps(tmp_path, client=FakeClient(FakeTokenizer(), respond=respond))
    )

    assert outcome.status == "succeeded", outcome.error
    results = {e.query_id: e for e in events(outcome) if isinstance(e, QueryResultEvent)}
    assert {q: (r.status, r.failure_reason) for q, r in results.items()} == {
        "val-001": ("not_delivered", "empty_output"),
        "val-002": ("not_delivered", "no_day_blocks"),
        "val-003": ("not_delivered", "no_fields"),
        "val-004": ("not_delivered", "length_no_plan"),
        "val-005": ("delivered", None),
    }
    parses = {e.query_id: e for e in events(outcome) if isinstance(e, ParseEvent)}
    assert parses["val-004"].failure_reason == "no_fields"  # the parser's own reason
    metrics = outcome.metrics
    assert metrics is not None
    assert metrics.non_delivery == {
        "llm_error": 0,
        "empty_output": 1,
        "length_no_plan": 1,
        "no_day_blocks": 1,
        "no_fields": 1,
    }
    assert (metrics.parse.attempted, metrics.parse.ok) == (5, 1)
    assert metrics.parse.failure_rate == 1 - 1 / 5
    assert metrics.metrics["Delivery Rate"].per_seed == {"0": 0.2}
    assert metrics.metrics["Delivery Rate"].sd is None  # one seed


# --- configs -------------------------------------------------------------------------------------


def test_a_single_run(tmp_path: Path) -> None:
    outcome = start_run(SINGLE_CONFIG_PATH, fake_deps(tmp_path))

    assert outcome.status == "succeeded", outcome.error
    assert "-single-" in outcome.run_id
    assert outcome.metrics is not None
    assert (outcome.metrics.kind, outcome.metrics.n_queries, outcome.metrics.seeds) == (
        "single",
        1,
        [0],
    )


def test_queries_run_in_query_id_order(tmp_path: Path) -> None:
    config = load_run_config(write_config(tmp_path / "c.yaml", queries=["val-003", "val-001"]))

    assert resolve_query_ids(config) == ["val-001", "val-003"]
    everything = load_run_config(write_config(tmp_path / "a.yaml", queries="all"))
    assert len(resolve_query_ids(everything)) == 180


def test_an_unknown_query_is_refused_before_anything_is_created(tmp_path: Path) -> None:
    config = write_config(tmp_path / "c.yaml", queries=["val-999"])
    deps = fake_deps(tmp_path)

    with pytest.raises(ValueError, match="unknown query ids"):
        start_run(config, deps)
    assert not deps.runs_dir.exists()
