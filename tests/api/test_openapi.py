"""``tripartite api export-openapi`` and ``serve``, and the committed contract (D8, D9)."""

import json
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from typer.testing import CliRunner

from tripartite import cli as root_cli
from tripartite.api.cli import app

runner = CliRunner()
CONTRACT = Path(__file__).resolve().parents[2] / "api-contract" / "openapi.json"


def _export() -> str:
    result = runner.invoke(app, ["export-openapi"])
    assert result.exit_code == 0, result.output
    return result.output


def test_export_is_deterministic_json_with_one_trailing_newline() -> None:
    first, second = _export(), _export()

    assert first == second
    assert first.endswith("}\n")
    assert not first.endswith("\n\n")
    json.loads(first)


def test_the_root_cli_exports_the_same_document() -> None:
    result = runner.invoke(root_cli.app, ["api", "export-openapi"])

    assert result.exit_code == 0, result.output
    assert result.output == _export()


def test_the_contract_has_exactly_the_f1_and_f2_operations() -> None:
    paths = json.loads(_export())["paths"]

    assert {path: set(ops) for path, ops in paths.items()} == {
        "/api/health": {"get"},
        "/api/queries": {"get"},
        "/api/queries/{query_id}": {"get"},
        "/api/runs": {"post"},
        "/api/runs/{run_id}": {"get"},
        "/api/runs/{run_id}/events": {"get"},
    }


D8_SCHEMAS = {
    "DayPlan": {
        "day",
        "current_city",
        "transportation",
        "breakfast",
        "attraction",
        "attractions",
        "lunch",
        "dinner",
        "accommodation",
    },
    "Constraint": {"key", "label", "group", "status", "message"},
    "Usage": {
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "load_ms",
        "prefill_ms",
        "generation_ms",
        "total_ms",
        "wall_ms",
    },
    "ItemDetail": {
        "query_id",
        "seed",
        "query",
        "delivered",
        "failure_reason",
        "plan",
        "constraints",
        "commonsense_pass",
        "hard_pass",
        "final_pass",
        "usage",
        "raw_output",
    },
    "RunDetail": {
        "run_id",
        "kind",
        "status",
        "stage",
        "created_at",
        "finished_at",
        "config_hash",
        "model",
        "prompt_version",
        "error",
        "item",
        "summary",
    },
    "ModelRef": {"tag", "digest"},
    "BatchSummary": {"progress", "metrics"},
    "MetricSummary": {"per_seed", "mean", "sd"},
    "RunRequest": {"query_id", "seed"},
    "RunAccepted": {"run_id", "status"},
    "RunConflict": {"detail", "active_run_id"},
}


def test_the_run_schemas_have_exactly_the_d8_fields_all_required() -> None:
    schemas = json.loads(_export())["components"]["schemas"]

    for name, fields in D8_SCHEMAS.items():
        assert set(schemas[name]["properties"]) == fields, name
        assert schemas[name]["additionalProperties"] is False, name
        if name != "RunRequest":
            assert set(schemas[name]["required"]) == fields, name
    assert schemas["RunRequest"]["required"] == ["query_id"]
    assert schemas["RunRequest"]["properties"]["seed"] == {
        "default": 0,
        "minimum": 0,
        "title": "Seed",
        "type": "integer",
    }


def test_the_closed_sets_are_d7s_and_d8s() -> None:
    schemas = json.loads(_export())["components"]["schemas"]
    detail = schemas["RunDetail"]["properties"]

    assert detail["kind"]["enum"] == ["batch", "single"]
    assert detail["status"]["enum"] == ["queued", "running", "succeeded", "failed", "interrupted"]
    stage, null = detail["stage"]["anyOf"]
    assert stage["enum"] == ["queued", "generating", "parsing", "evaluating", "done"]
    assert null == {"type": "null"}
    constraint = schemas["Constraint"]["properties"]
    assert constraint["group"]["enum"] == ["commonsense", "hard"]
    assert constraint["status"]["enum"] == ["pass", "fail", "not_applicable", "not_evaluated"]
    assert schemas["RunAccepted"]["properties"]["status"]["const"] == "queued"


def test_the_run_routes_document_their_responses() -> None:
    paths = json.loads(_export())["paths"]

    def ref(path: str, method: str, status: str, media: str = "application/json") -> str:
        schema = paths[path][method]["responses"][status]["content"][media]["schema"]
        return str(schema["$ref"]).rsplit("/", 1)[-1]

    post = paths["/api/runs"]["post"]["responses"]
    assert set(post) == {"202", "404", "409", "422", "503"}
    assert ref("/api/runs", "post", "202") == "RunAccepted"
    assert ref("/api/runs", "post", "404") == "ErrorDetail"
    assert ref("/api/runs", "post", "409") == "RunConflict"
    assert ref("/api/runs", "post", "503") == "ErrorDetail"
    assert ref("/api/runs/{run_id}", "get", "200") == "RunDetail"
    assert ref("/api/runs/{run_id}", "get", "404") == "ErrorDetail"
    events = paths["/api/runs/{run_id}/events"]["get"]["responses"]
    assert set(events["200"]["content"]) == {"text/event-stream"}
    assert "404" in events


def test_the_query_schema_exposes_only_planner_input_fields() -> None:
    schemas = json.loads(_export())["components"]["schemas"]

    assert set(schemas["QueryItem"]["properties"]) == {"query_id", "query"}
    assert set(schemas["Health"]["properties"]) == {
        "status",
        "model_reachable",
        "model_digest_ok",
        "evaluator_ready",
    }


def test_the_committed_contract_equals_the_export() -> None:
    assert CONTRACT.read_text(encoding="utf-8") == _export(), "run `make openapi`"


def test_serve_runs_uvicorn_on_the_d8_address(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    assert calls == [(("tripartite.api.app:app",), {"host": "127.0.0.1", "port": 8000})]
