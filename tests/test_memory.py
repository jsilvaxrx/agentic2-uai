from fastapi.testclient import TestClient

from api.app import app
from src.router.tools import open_checkpointer


def test_checkpointer_falls_back_to_ram_without_database_url() -> None:
    handle = open_checkpointer("")
    try:
        assert handle.mode == "ram"
        assert handle.fallback_reason == "DATABASE_URL no está configurada."
    finally:
        handle.close()


def test_health_reports_ram_when_database_url_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["memoria"] == "ram"
