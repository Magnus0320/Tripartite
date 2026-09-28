"""``GET /api/queries`` and ``GET /api/queries/{query_id}`` on the synthetic set (D8, D3)."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import synthetic_data
from tripartite.api.schemas import QueryItem
from tripartite.data.planner_inputs import PlannerInput

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


def test_the_query_model_has_only_planner_input_fields() -> None:
    planner_fields = {f.name for f in dataclasses.fields(PlannerInput)}

    assert set(QueryItem.model_fields) == ALLOWED
    assert planner_fields - ALLOWED == {"reference_information"}
