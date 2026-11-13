"""Modelos y dependencias externas del agente router."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field
from psycopg_pool import ConnectionPool


class Decision(BaseModel):
    ruta: Literal["preventa", "postventa", "generica"] = Field(
        description="A qué agente va el mensaje."
    )
    motivo: str = Field(description="Una frase: por qué esa ruta.")


@dataclass
class CheckpointerHandle:
    checkpointer: Any
    mode: Literal["ram", "postgres"]
    pool: ConnectionPool | None = None
    fallback_reason: str | None = None

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()


def create_llm() -> ChatGoogleGenerativeAI:
    """Crea el modelo de Gemini configurado mediante variables de entorno."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("MODELO", "gemini-3.5-flash-lite"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def open_checkpointer(database_url: str | None = None) -> CheckpointerHandle:
    """Abre Postgres y crea sus tablas; ante un fallo conserva el router en RAM."""
    database_url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if not database_url:
        return CheckpointerHandle(
            checkpointer=MemorySaver(),
            mode="ram",
            fallback_reason="DATABASE_URL no está configurada.",
        )

    pool: ConnectionPool | None = None
    try:
        pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=2,
            max_waiting=2,
            timeout=5,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        pool.open(wait=True, timeout=5)
        pool.check()
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        return CheckpointerHandle(
            checkpointer=checkpointer,
            mode="postgres",
            pool=pool,
        )
    except Exception as error:
        if pool is not None:
            pool.close()
        return CheckpointerHandle(
            checkpointer=MemorySaver(),
            mode="ram",
            fallback_reason=f"Postgres no está disponible ({type(error).__name__}).",
        )
