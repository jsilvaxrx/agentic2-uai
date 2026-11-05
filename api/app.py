"""API HTTP para enrutar conversaciones del ecommerce."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from src.router.graph import create_graph

load_dotenv()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    ok: bool = Field(description="Indica que la API está disponible.", examples=[True])
    modelo: str = Field(
        description="Modelo Gemini configurado para el router.",
        examples=["gemini-3.5-flash-lite"],
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
        description="Respuesta del agente cascarón seleccionado.",
        examples=["Soy el agente de preventa. Recibí: ¿Tienen la polera azul en talla M?. Pronto podré ayudarte con productos y compras."],
    )


class ErrorResponse(BaseModel):
    detail: str = Field(
        description="Mensaje seguro para el cliente.",
        examples=["No fue posible procesar el mensaje en este momento."],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.router_graph = create_graph()
    yield


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
def health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        modelo=os.getenv("MODELO", "gemini-3.5-flash-lite"),
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Enviar un mensaje al router",
    responses={
        200: {"description": "Mensaje enrutado correctamente."},
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
def chat(chat_request: ChatRequest, request: Request) -> ChatResponse:
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


@app.post("/telegram", include_in_schema=False, tags=["telegram"])
def telegram(_: Any = Body(...)) -> dict[str, bool]:
    return {"ok": True}
