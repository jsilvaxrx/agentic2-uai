"""Modelos y dependencias externas del agente router."""

from __future__ import annotations

import os
from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field


class Decision(BaseModel):
    ruta: Literal["preventa", "postventa", "generica"] = Field(
        description="A qué agente va el mensaje."
    )
    motivo: str = Field(description="Una frase: por qué esa ruta.")


def create_llm() -> ChatGoogleGenerativeAI:
    """Crea el modelo de Gemini configurado mediante variables de entorno."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("MODELO", "gemini-3.5-flash-lite"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )
