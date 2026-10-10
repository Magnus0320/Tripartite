"""``GET /api/queries`` and ``GET /api/queries/{query_id}`` on the synthetic set (D8, D3)."""

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.helpers import NO_VALIDATION_CSV, assert_no_absolute_path
from tests.fixtures import synthetic_data
from tripartite.api.messages import public_message
from tripartite.api.schemas import QueryItem
from tripartite.data.manifest import VALIDATION_REF_INFO, DataError
from tripartite.data.planner_inputs import PlannerInput, load_planner_inputs

ROWS = range(1, 181)
ALLOWED = {"query_id", "query"}


def test_lists_all_180_queries_in_order_with_only_the_two_allowed_fields(
    client: TestClient,
) -> None:
    response = client.get("/api/queries")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items"}
    items = body["items"]
    assert [item["query_id"] for item in items] == [f"val-{i:03d}" for i in ROWS]
    assert all(set(item) == ALLOWED for item in items)
    assert [item["query"] for item in items] == [synthetic_data.query(i) for i in ROWS]


def test_no_evaluator_only_value_or_reference_information_is_served(client: TestClient) -> None:
    text = client.get("/api/queries").text

    for i in ROWS:
        for canary in synthetic_data.canaries(i):
            assert canary not in text
    assert "Synthville" not in text  # every reference_information line names it


@pytest.mark.parametrize("query_id", ["val-001", "val-090", "val-180"])
def test_one_query_equals_its_list_item(client: TestClient, query_id: str) -> None:
    listed = {item["query_id"]: item for item in client.get("/api/queries").json()["items"]}

    response = client.get(f"/api/queries/{query_id}")

    assert response.status_code == 200
    assert response.json() == listed[query_id]
    assert set(response.json()) == ALLOWED


@pytest.mark.parametrize("query_id", ["val-000", "val-181", "test-001", "VAL-001", "val-1"])
def test_an_unknown_query_id_is_404(client: TestClient, query_id: str) -> None:
    response = client.get(f"/api/queries/{query_id}")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail"}
    assert query_id in body["detail"]


@pytest.mark.parametrize("path", ["/api/queries", "/api/queries/val-001"])
def test_an_empty_data_dir_is_503_with_the_loaders_message_and_no_absolute_path(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))
    with pytest.raises(FileNotFoundError) as raised:
        load_planner_inputs()

    response = client.get(path)

    assert response.status_code == 503
    assert str(empty / "raw" / "validation.csv") in str(raised.value)
    assert response.json() == {"detail": NO_VALIDATION_CSV}
    assert_no_absolute_path(response.text, tmp_path)


@pytest.mark.parametrize("path", ["/api/queries", "/api/queries/val-001"])
def test_a_data_error_is_503_with_its_message_and_no_absolute_path(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(missing))
    with pytest.raises(DataError) as raised:
        load_planner_inputs()

    response = client.get(path)

    assert response.status_code == 503
    assert str(missing) in str(raised.value)
    assert response.json() == {
        "detail": "TRIPARTITE_DATA_DIR must be an existing directory, got 'missing'"
    }
    assert_no_absolute_path(response.text, tmp_path)


@pytest.mark.parametrize("path", ["/api/queries", "/api/queries/val-001"])
def test_invalid_data_is_503_with_the_loaders_message(
    client: TestClient, synthetic_data: Path, tmp_path: Path, path: str
) -> None:
    ref_info = synthetic_data / "raw" / VALIDATION_REF_INFO
    lines = ref_info.read_bytes().split(b"\n")
    ref_info.write_bytes(b"\n".join(lines[:100]) + b"\n")
    with pytest.raises(ValueError, match="has 100 lines") as raised:
        load_planner_inputs()

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": public_message(str(raised.value))}
    assert "has 100 lines" in response.json()["detail"]
    assert_no_absolute_path(response.text, tmp_path)


def test_an_unknown_query_id_is_still_404_not_503(client: TestClient) -> None:
    assert client.get("/api/queries/val-999").status_code == 404


def test_the_query_model_has_only_planner_input_fields() -> None:
    planner_fields = {f.name for f in dataclasses.fields(PlannerInput)}

    assert set(QueryItem.model_fields) == ALLOWED
    assert planner_fields - ALLOWED == {"reference_information"}
