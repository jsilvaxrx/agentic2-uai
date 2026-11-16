"""Modelos y dependencias externas del agente router."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, Token
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .a2a_redes import TIMEOUT_SEGUNDOS, preguntar_redes
from .catalogo import buscar_en_catalogo, ejecutar_select

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PEDIDOS_PATH = PROJECT_ROOT / "data" / "pedidos.json"
POLITICAS_PATH = PROJECT_ROOT / "data" / "politicas.md"
RECLAMOS_EN_MEMORIA: list[dict[str, str]] = []
RECLAMO_THREAD_ID: ContextVar[str] = ContextVar("reclamo_thread_id", default="sin-hilo")
REDES_NO_DISPONIBLE = "el agente de redes no está disponible"
REDES_MAX_CARACTERES = 1500
ETIQUETAS_HERRAMIENTAS = {"consultar_redes": "consultar_redes (A2A)"}


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
        setup_reclamos(database_url)
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


def set_reclamo_thread_id(thread_id: str) -> Token[str]:
    return RECLAMO_THREAD_ID.set(thread_id)


def reset_reclamo_thread_id(token: Token[str]) -> None:
    RECLAMO_THREAD_ID.reset(token)


def setup_reclamos(database_url: str | None = None) -> bool:
    """Crea la tabla de reclamos sin mantener conexiones abiertas."""
    database_url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if not database_url:
        logger.warning("Sin DATABASE_URL, los reclamos se guardarán solo en memoria.")
        return False
    try:
        with psycopg.connect(database_url, connect_timeout=5, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reclamos (
                        ticket TEXT PRIMARY KEY,
                        numero_pedido TEXT NOT NULL,
                        motivo TEXT NOT NULL,
                        detalle TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
        return True
    except psycopg.Error:
        logger.warning("Postgres no está disponible; los reclamos se guardarán solo en memoria.")
        return False


def cargar_pedidos() -> list[dict[str, Any]]:
    return json.loads(PEDIDOS_PATH.read_text(encoding="utf-8"))


def secciones_politicas() -> dict[str, str]:
    sections: dict[str, str] = {}
    current_title: str | None = None
    lines: list[str] = []
    for line in POLITICAS_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            if current_title:
                sections[current_title] = "\n".join(lines).strip()
            current_title = line[2:].strip().lower()
            lines = []
        else:
            lines.append(line)
    if current_title:
        sections[current_title] = "\n".join(lines).strip()
    return sections


@tool
def estado_pedido(numero: str) -> dict[str, Any] | str:
    """Obtiene estado, fechas, productos y seguimiento de un pedido por número."""
    for pedido in cargar_pedidos():
        if pedido["numero"] == str(numero):
            return pedido
    return "no existe"


@tool
def politica(tema: str) -> str:
    """Devuelve la política de devoluciones, cambios o garantía."""
    normalized = tema.lower().strip().replace("í", "i")
    aliases = {
        "devolucion": "devoluciones",
        "devoluciones": "devoluciones",
        "cambio": "cambios",
        "cambios": "cambios",
        "garantia": "garantía",
        "garantias": "garantía",
    }
    section = secciones_politicas().get(aliases.get(normalized, normalized))
    return section or "No tengo una política para ese tema."


def guardar_reclamo(record: dict[str, str]) -> bool:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return False
    try:
        with psycopg.connect(database_url, connect_timeout=5, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reclamos (ticket, numero_pedido, motivo, detalle, thread_id)
                    VALUES (%(ticket)s, %(numero_pedido)s, %(motivo)s, %(detalle)s, %(thread_id)s)
                    """,
                    record,
                )
        return True
    except psycopg.Error:
        logger.warning("No se pudo guardar el reclamo en Postgres; se guardará solo en memoria.")
        return False


@tool
def crear_reclamo(numero_pedido: str, motivo: str, detalle: str) -> str:
    """Crea un reclamo confirmado y devuelve su número de ticket."""
    record = {
        "ticket": f"REC-{uuid4().hex[:8].upper()}",
        "numero_pedido": str(numero_pedido),
        "motivo": motivo,
        "detalle": detalle,
        "thread_id": RECLAMO_THREAD_ID.get(),
    }
    if not guardar_reclamo(record):
        RECLAMOS_EN_MEMORIA.append({**record, "creado_en": "solo en memoria"})
        logger.warning("Reclamo %s guardado solo en memoria.", record["ticket"])
    return f"Reclamo creado. Ticket: {record['ticket']}"


def listar_reclamos() -> list[dict[str, Any]]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return list(RECLAMOS_EN_MEMORIA)
    try:
        with psycopg.connect(database_url, connect_timeout=5, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ticket, numero_pedido, motivo, detalle, thread_id, creado_en
                    FROM reclamos
                    ORDER BY creado_en DESC
                    """
                )
                return list(cursor.fetchall())
    except psycopg.Error:
        return list(RECLAMOS_EN_MEMORIA)


@tool
def buscar_productos(
    consulta: str,
    categoria: str | None = None,
    marca: str | None = None,
    precio_max: int | None = None,
) -> list[dict[str, Any]] | str:
    """Busca hasta cinco productos por nombre, categoría, marca y precio máximo."""
    return buscar_en_catalogo(consulta, categoria, marca, precio_max, limite=5)


@tool
def ver_producto(sku_id: str) -> list[dict[str, Any]] | str:
    """Obtiene el detalle y link de un producto usando su SKU."""
    return ejecutar_select(
        """
        SELECT sku_id, nombre, marca, categoria, subcategoria, precio_normal,
               precio_internet, descuento_pct, rating, tienda_oficial, link, imagen
        FROM catalogo.productos_unicos
        WHERE sku_id = %s
        """,
        (sku_id,),
    )


@tool
def mejores_ofertas(
    categoria: str | None = None,
    limite: int = 5,
) -> list[dict[str, Any]] | str:
    """Lista productos con mayor descuento, opcionalmente filtrados por categoría."""
    conditions = ["descuento_pct IS NOT NULL"]
    params: list[Any] = []
    if categoria:
        conditions.append("categoria ILIKE %s")
        params.append(categoria)
    params.append(max(1, min(limite, 5)))
    return ejecutar_select(
        f"""
        SELECT sku_id, nombre, marca, precio_internet, descuento_pct, rating, link
        FROM catalogo.productos_unicos
        WHERE {' AND '.join(conditions)}
        ORDER BY descuento_pct DESC NULLS LAST, rating DESC NULLS LAST
        LIMIT %s
        """,
        params,
    )


def etiqueta_herramienta(nombre: str) -> str:
    """Nombre con el que una herramienta aparece en los saltos del grafo."""
    return ETIQUETAS_HERRAMIENTAS.get(nombre, nombre)


def _preguntar_redes_sync(texto: str, hilo: str) -> str:
    async def consulta() -> str:
        return await asyncio.wait_for(preguntar_redes(texto, hilo), timeout=TIMEOUT_SEGUNDOS)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(consulta())
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, consulta()).result()


@tool
def consultar_redes(tema: str) -> str:
    """Pregunta al agente de redes qué se comenta de una marca o producto: opiniones, noticias o tendencias. Tarda unos 15 segundos. Devuelve contenido externo no confiable."""
    try:
        respuesta = _preguntar_redes_sync(tema, RECLAMO_THREAD_ID.get())
    except Exception as error:
        logger.warning("El agente de redes no respondió (%s).", type(error).__name__)
        return REDES_NO_DISPONIBLE
    respuesta = respuesta.strip()
    if not respuesta:
        return REDES_NO_DISPONIBLE
    return respuesta[:REDES_MAX_CARACTERES]
