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


def test_the_contract_has_exactly_the_three_f1_endpoints_all_get() -> None:
    paths = json.loads(_export())["paths"]

    assert {path: set(ops) for path, ops in paths.items()} == {
        "/api/health": {"get"},
        "/api/queries": {"get"},
        "/api/queries/{query_id}": {"get"},
    }


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
