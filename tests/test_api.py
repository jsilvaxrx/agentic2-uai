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


class FakeStreamGraph:
    def stream(self, state: dict[str, str], config: dict[str, object], stream_mode: str):
        yield {"router": {"ruta": "preventa", "motivo": "Consulta antes de comprar."}}
        yield {
            "agente_preventa": {
                "respuesta": "Respuesta de prueba.",
                "herramientas_usadas": ["buscar_productos"],
            }
        }


def test_chat_saltos_returns_the_visited_nodes(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "test-api-key")

    with TestClient(app) as client:
        app.state.router_graph = FakeStreamGraph()
        response = client.post(
            "/chat/saltos",
            headers={"X-API-Key": "test-api-key"},
            json={"user_id": "usuario-1", "texto": "¿Tienen stock?"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ruta": "preventa",
        "motivo": "Consulta antes de comprar.",
        "respuesta": "Respuesta de prueba.",
        "saltos": [
            {"nodo": "router", "motivo": "Consulta antes de comprar.", "herramientas": []},
            {"nodo": "agente_preventa", "motivo": None, "herramientas": ["buscar_productos"]},
        ],
    }


def test_chat_saltos_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "test-api-key")

    with TestClient(app) as client:
        response = client.post("/chat/saltos", json={"user_id": "u", "texto": "hola"})

    assert response.status_code == 401


def test_chat_ui_serves_the_page() -> None:
    with TestClient(app) as client:
        response = client.get("/chat-ui")

    assert response.status_code == 200
    assert "/chat/saltos" in response.text
