"""``GET /api/health`` (D8)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_health_has_exactly_the_d8_fields(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    # The three checks are not defined or not on main yet (F1 Architecture questions), so the
    # server claims none of them.
    assert response.json() == {
        "status": "ok",
        "model_reachable": False,
        "model_digest_ok": False,
        "evaluator_ready": False,
    }


def test_health_does_not_read_the_data(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("TRIPARTITE_DATA_DIR", str(empty))

    assert client.get("/api/health").status_code == 200
