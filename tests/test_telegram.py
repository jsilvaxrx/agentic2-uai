from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app


class FakeGraph:
    def __init__(self) -> None:
        self.inputs: list[tuple[dict[str, str], dict[str, object]]] = []

    def invoke(self, state: dict[str, str], config: dict[str, object]) -> dict[str, str]:
        self.inputs.append((state, config))
        return {
            "ruta": "preventa",
            "motivo": "Consulta antes de comprar.",
            "respuesta": "Respuesta de prueba.",
        }


class FakeTelegramResponse:
    def raise_for_status(self) -> None:
        return None


def test_telegram_routes_and_replies_with_chat_id(monkeypatch) -> None:
    graph = FakeGraph()
    sent: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: float):
        sent.update({"url": url, "json": json, "timeout": timeout})
        return FakeTelegramResponse()

    monkeypatch.setenv("TELEGRAM_SECRET", "test-secret")
    monkeypatch.setenv("TELEGRAM_TOKEN", "test-token")
    monkeypatch.setattr("api.app.httpx.post", fake_post)

    with TestClient(app) as client:
        app.state.router_graph = graph
        response = client.post(
            "/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            json={"message": {"chat": {"id": 12345}, "text": "¿Tienen stock?"}},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert graph.inputs[0][0] == {"mensaje": "¿Tienen stock?"}
    assert graph.inputs[0][1] == {"configurable": {"thread_id": "12345"}}
    assert sent["json"] == {"chat_id": 12345, "text": "Respuesta de prueba."}


def test_telegram_rejects_an_invalid_secret(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_SECRET", "test-secret")

    with TestClient(app) as client:
        response = client.post("/telegram", json={})

    assert response.status_code == 403


def test_telegram_ignores_updates_without_text(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_SECRET", "test-secret")

    with TestClient(app) as client:
        response = client.post(
            "/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            json={"callback_query": {"id": "1"}},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
