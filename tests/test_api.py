from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app


class FakeGraph:
    def invoke(self, state: dict[str, str], config: dict[str, object]) -> dict[str, str]:
        return {
            "ruta": "preventa",
            "motivo": "Consulta antes de comprar.",
            "respuesta": "Respuesta de prueba.",
        }


def test_chat_rejects_requests_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "test-api-key")

    with TestClient(app) as client:
        response = client.post(
            "/chat", json={"user_id": "usuario-1", "texto": "hola"}
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Se requiere una X-API-Key válida."}


def test_chat_accepts_a_valid_api_key(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "test-api-key")

    with TestClient(app) as client:
        app.state.router_graph = FakeGraph()
        response = client.post(
            "/chat",
            headers={"X-API-Key": "test-api-key"},
            json={"user_id": "usuario-1", "texto": "¿Tienen stock?"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ruta": "preventa",
        "motivo": "Consulta antes de comprar.",
        "respuesta": "Respuesta de prueba.",
    }
