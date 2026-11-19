"""API HTTP para enrutar conversaciones del ecommerce."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import secrets
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Request, Security
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
import httpx
from pydantic import BaseModel, Field

from src.router.graph import create_graph
from src.router.tools import open_checkpointer

load_dotenv()
logger = logging.getLogger(__name__)
CHAT_UI_PATH = Path(__file__).with_name("chat_ui.html")
api_key_header = APIKeyHeader(name="X-API-Key", scheme_name="APIKeyHeader", auto_error=False)


class HealthResponse(BaseModel):
    ok: bool = Field(description="Indica que la API está disponible.", examples=[True])
    modelo: str = Field(
        description="Modelo Gemini configurado para el router.",
        examples=["gemini-3.5-flash-lite"],
    )
    memoria: Literal["ram", "postgres"] = Field(
        description="Checkpointer activo para las conversaciones.", examples=["postgres"]
    )


class ChatRequest(BaseModel):
    user_id: str = Field(
        min_length=1,
        description="Identificador estable del usuario; se usa como thread_id de LangGraph.",
        examples=["usuario-123"],
    )
    texto: str = Field(
        min_length=1,
        description="Mensaje que se enviará al router del ecommerce.",
        examples=["¿Tienen la polera azul en talla M?"],
    )


class ChatResponse(BaseModel):
    ruta: Literal["preventa", "postventa", "generica"] = Field(
        description="Agente seleccionado por el router.", examples=["preventa"]
    )
    motivo: str = Field(
        description="Motivo breve que explica la ruta elegida.",
        examples=["Consulta por talla y disponibilidad antes de comprar."],
    )
    respuesta: str = Field(
        description="Respuesta del agente seleccionado, basada en sus herramientas y el historial.",
        examples=["¿Qué presupuesto tienes para tu celular?"],
    )


class Salto(BaseModel):
    nodo: str = Field(description="Nodo del grafo que se ejecutó.", examples=["router"])
    motivo: str | None = Field(
        default=None, description="Motivo de la ruta; solo lo informa el nodo router."
    )
    herramientas: list[str] = Field(
        default_factory=list, description="Herramientas que usó el nodo, en orden."
    )


class ChatSaltosResponse(ChatResponse):
    saltos: list[Salto] = Field(description="Nodos recorridos por el grafo, en orden.")


class ErrorResponse(BaseModel):
    detail: str = Field(
        description="Mensaje seguro para el cliente.",
        examples=["No fue posible procesar el mensaje en este momento."],
    )


class WebhookTestRequest(BaseModel):
    user_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    tipo: Literal["texto", "voz", "gif"]


def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    expected_key = os.getenv("API_KEY")
    if not expected_key or not api_key or not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(status_code=401, detail="Se requiere una X-API-Key válida.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer_handle = open_checkpointer()
    if checkpointer_handle.fallback_reason:
        logger.warning("Se usará memoria RAM: %s", checkpointer_handle.fallback_reason)
    app.state.memory_mode = checkpointer_handle.mode
    app.state.router_graph = create_graph(checkpointer=checkpointer_handle.checkpointer)
    try:
        yield
    finally:
        checkpointer_handle.close()


app = FastAPI(
    title="Ecommerce Router API",
    version="1.0.0",
    description=(
        "Enruta mensajes del chat de ecommerce hacia **preventa**, **postventa** "
        "o **generica**. Conserva el historial por usuario mediante LangGraph."
    ),
    openapi_tags=[
        {"name": "salud", "description": "Disponibilidad y modelo configurado."},
        {"name": "chat", "description": "Enrutamiento de mensajes del ecommerce."},
        {"name": "telegram", "description": "Webhook reservado para Telegram."},
    ],
    lifespan=lifespan,
)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["salud"],
    summary="Consultar el estado de la API",
)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        ok=True,
        modelo=os.getenv("MODELO", "gemini-3.5-flash-lite"),
        memoria=getattr(request.app.state, "memory_mode", "ram"),
    )


@app.get("/webhook-tester", include_in_schema=False, response_class=HTMLResponse)
def webhook_tester() -> str:
    return """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Webhook Tester</title>
<style>body{font-family:system-ui;max-width:680px;margin:48px auto;padding:0 20px}label{display:block;margin-top:16px;font-weight:600}input,select,textarea,button{box-sizing:border-box;width:100%;padding:10px;margin-top:6px;font:inherit}textarea{min-height:120px}button{background:#171717;color:#fff;border:0;cursor:pointer;margin-top:24px}pre{white-space:pre-wrap;background:#f4f4f5;padding:16px;border-radius:8px}</style>
</head><body><h1>Webhook tester</h1><p>Prueba el flujo n8n de texto, voz simulada o GIF.</p>
<label>API key<input id="key" type="password" placeholder="Tu API_KEY local"></label>
<label>User ID<input id="user" value="web-local-1"></label>
<label>Tipo<select id="type"><option value="texto">Texto</option><option value="voz">Voz simulada</option><option value="gif">GIF</option></select></label>
<label>Texto o transcripción<textarea id="text">¿Tienen la polera azul en talla M?</textarea></label>
<button id="send">Enviar al webhook</button><pre id="result">Esperando prueba.</pre>
<script>
document.getElementById('send').onclick = async () => {
  const result = document.getElementById('result');
  result.textContent = 'Enviando...';
  const response = await fetch('/webhook-tester/send', {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-API-Key': document.getElementById('key').value},
    body: JSON.stringify({user_id: document.getElementById('user').value, texto: document.getElementById('text').value, tipo: document.getElementById('type').value})
  });
  result.textContent = JSON.stringify(await response.json(), null, 2);
};
</script></body></html>"""


@app.post("/webhook-tester/send", include_in_schema=False)
def send_webhook_test(
    payload: WebhookTestRequest,
    _: None = Security(require_api_key),
) -> dict[str, Any]:
    webhook_url = os.getenv("N8N_WEBHOOK_URL")
    if not webhook_url:
        raise HTTPException(status_code=503, detail="N8N_WEBHOOK_URL no está configurada.")

    try:
        response = httpx.post(webhook_url, json=payload.model_dump(), timeout=35.0)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("No se pudo llamar al webhook de prueba de n8n.")
        raise HTTPException(status_code=502, detail="El webhook de n8n no respondió correctamente.") from None

    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return {"ok": True, "webhook_response": body}


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Enviar un mensaje al router",
    responses={
        200: {"description": "Mensaje enrutado correctamente."},
        401: {"description": "Falta la clave de API o no es válida.", "model": ErrorResponse},
        422: {"description": "El cuerpo no cumple el formato requerido."},
        502: {
            "description": "El modelo no pudo procesar el mensaje.",
            "model": ErrorResponse,
        },
    },
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "user_id": "usuario-123",
                        "texto": "¿Tienen la polera azul en talla M?",
                    }
                }
            }
        }
    },
)
def chat(
    chat_request: ChatRequest,
    request: Request,
    _: None = Security(require_api_key),
) -> ChatResponse:
    try:
        result = request.app.state.router_graph.invoke(
            {"mensaje": chat_request.texto},
            config={"configurable": {"thread_id": chat_request.user_id}},
        )
    except Exception:
        logger.exception("El router falló al procesar el mensaje del usuario %s", chat_request.user_id)
        raise HTTPException(
            status_code=502,
            detail="No fue posible procesar el mensaje en este momento. Inténtalo nuevamente.",
        ) from None

    return ChatResponse(
        ruta=result["ruta"],
        motivo=result["motivo"],
        respuesta=result["respuesta"],
    )


@app.get("/chat-ui", include_in_schema=False, response_class=HTMLResponse)
def chat_ui() -> str:
    return CHAT_UI_PATH.read_text(encoding="utf-8")


@app.post(
    "/chat/saltos",
    response_model=ChatSaltosResponse,
    tags=["chat"],
    summary="Enviar un mensaje y ver los nodos recorridos",
    responses={
        401: {"description": "Falta la clave de API o no es válida.", "model": ErrorResponse},
        502: {"description": "El modelo no pudo procesar el mensaje.", "model": ErrorResponse},
    },
)
def chat_saltos(
    chat_request: ChatRequest,
    request: Request,
    _: None = Security(require_api_key),
) -> ChatSaltosResponse:
    saltos: list[Salto] = []
    result: dict[str, Any] = {}
    try:
        for event in request.app.state.router_graph.stream(
            {"mensaje": chat_request.texto},
            config={"configurable": {"thread_id": chat_request.user_id}},
            stream_mode="updates",
        ):
            for node, update in event.items():
                update = update or {}
                result.update(update)
                saltos.append(
                    Salto(
                        nodo=node,
                        motivo=update.get("motivo"),
                        herramientas=update.get("herramientas_usadas", []),
                    )
                )
        response = ChatSaltosResponse(
            ruta=result["ruta"],
            motivo=result["motivo"],
            respuesta=result["respuesta"],
            saltos=saltos,
        )
    except Exception:
        logger.exception("El router falló al procesar el mensaje del usuario %s", chat_request.user_id)
        raise HTTPException(
            status_code=502,
            detail="No fue posible procesar el mensaje en este momento. Inténtalo nuevamente.",
        ) from None
    return response


@app.post("/telegram", include_in_schema=False, tags=["telegram"])
def telegram(
    request: Request,
    update: Any = Body(...),
    secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> dict[str, bool]:
    expected_secret = os.getenv("TELEGRAM_SECRET")
    if (
        not expected_secret
        or not secret_token
        or not secrets.compare_digest(secret_token, expected_secret)
    ):
        logger.warning("Webhook de Telegram rechazado por secreto inválido.")
        raise HTTPException(status_code=403, detail="Webhook de Telegram no autorizado.")

    if not isinstance(update, dict):
        return {"ok": True}

    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return {"ok": True}

    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        return {"ok": True}

    chat_id = chat["id"]
    try:
        result = request.app.state.router_graph.invoke(
            {"mensaje": message["text"]},
            config={"configurable": {"thread_id": str(chat_id)}},
        )
        logger.info("Telegram chat %s enrutado a %s: %s", chat_id, result["ruta"], result["motivo"])
    except Exception:
        logger.exception("El router falló al procesar el chat de Telegram %s", chat_id)
        return {"ok": True}

    telegram_token = os.getenv("TELEGRAM_TOKEN")
    if not telegram_token:
        logger.error("TELEGRAM_TOKEN no está configurado; no se pudo responder al chat %s", chat_id)
        return {"ok": True}

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{telegram_token}/sendMessage",
            json={"chat_id": chat_id, "text": result["respuesta"]},
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("No se pudo enviar la respuesta de Telegram al chat %s", chat_id)

    return {"ok": True}
