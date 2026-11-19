"""Modelos y dependencias externas del agente router."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Iterator, Literal
import unicodedata
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .catalogo import buscar_en_catalogo, ejecutar_select

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PEDIDOS_PATH = PROJECT_ROOT / "data" / "pedidos.json"
POLITICAS_PATH = PROJECT_ROOT / "data" / "politicas.md"
RECLAMOS_EN_MEMORIA: list[dict[str, str]] = []
RECLAMO_THREAD_ID: ContextVar[str] = ContextVar("reclamo_thread_id", default="sin-hilo")
_CONEXION_RECLAMOS = BoundedSemaphore(1)


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
    # Los reclamos se inicializan aunque falle el checkpointer o se use RAM.
    setup_reclamos(database_url)
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


def set_reclamo_thread_id(thread_id: str) -> Token[str]:
    return RECLAMO_THREAD_ID.set(thread_id)


def reset_reclamo_thread_id(token: Token[str]) -> None:
    RECLAMO_THREAD_ID.reset(token)


@contextmanager
def conexion_reclamos(database_url: str) -> Iterator[psycopg.Connection]:
    """Usa como máximo una conexión de reclamos y la cierra al terminar."""
    if not _CONEXION_RECLAMOS.acquire(timeout=5):
        raise psycopg.OperationalError("No hay conexión de reclamos disponible.")
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            autocommit=True,
            row_factory=dict_row,
            options="-c statement_timeout=5000",
        ) as connection:
            yield connection
    finally:
        _CONEXION_RECLAMOS.release()


def setup_reclamos(database_url: str | None = None) -> bool:
    """Crea la tabla de reclamos sin mantener conexiones abiertas."""
    database_url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if not database_url:
        logger.warning("Sin DATABASE_URL, los reclamos se guardarán solo en memoria.")
        return False
    try:
        with conexion_reclamos(database_url) as connection:
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
    numero = str(numero).strip().removeprefix("#").strip()
    try:
        pedidos = cargar_pedidos()
    except (OSError, json.JSONDecodeError):
        logger.warning("Los datos de pedidos no están disponibles.")
        return "pedidos no disponibles"
    for pedido in pedidos:
        if str(pedido["numero"]) == numero:
            return pedido
    return "no existe"


@tool
def politica(tema: str) -> str:
    """Devuelve la política de devoluciones, cambios o garantía."""
    normalized = "".join(
        letra for letra in unicodedata.normalize("NFKD", tema.lower().strip())
        if not unicodedata.combining(letra)
    )
    aliases = {
        "devolucion": "devoluciones",
        "devoluciones": "devoluciones",
        "cambio": "cambios",
        "cambios": "cambios",
        "garantia": "garantía",
        "garantias": "garantía",
    }
    try:
        section = secciones_politicas().get(aliases.get(normalized, normalized))
    except OSError:
        logger.warning("Las políticas de postventa no están disponibles.")
        return "políticas no disponibles"
    return section or "No tengo una política para ese tema."


def guardar_reclamo(record: dict[str, str]) -> bool:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return False
    try:
        with conexion_reclamos(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reclamos
                        (ticket, numero_pedido, motivo, detalle, thread_id, creado_en)
                    VALUES
                        (%(ticket)s, %(numero_pedido)s, %(motivo)s, %(detalle)s,
                         %(thread_id)s, %(creado_en)s)
                    """,
                    record,
                )
        return True
    except psycopg.Error:
        logger.warning("No se pudo guardar el reclamo en Postgres; se guardará solo en memoria.")
        return False


@tool
def crear_reclamo(
    numero_pedido: str, motivo: str, detalle: str, config: RunnableConfig,
) -> str:
    """Crea un reclamo después de que el cliente confirme el motivo.

    Usa un número de pedido consultado con estado_pedido. Para atención humana
    o casos fuera de las políticas, motivo debe ser exactamente 'derivar a persona'.
    Devuelve el ticket registrado; no inventes un ticket por tu cuenta.
    """
    record = {
        "ticket": f"REC-{uuid4().hex[:8].upper()}",
        "numero_pedido": str(numero_pedido).strip().removeprefix("#").strip(),
        "motivo": motivo,
        "detalle": detalle,
        "thread_id": str(
            config.get("configurable", {}).get("thread_id", RECLAMO_THREAD_ID.get())
        ),
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }
    if not guardar_reclamo(record):
        RECLAMOS_EN_MEMORIA.append(record)
        logger.warning("Reclamo %s guardado solo en memoria.", record["ticket"])
    return f"Reclamo creado. Ticket: {record['ticket']}"


def listar_reclamos() -> list[dict[str, Any]]:
    database_url = os.getenv("DATABASE_URL")
    en_memoria = list(RECLAMOS_EN_MEMORIA)
    if not database_url:
        logger.warning("Sin DATABASE_URL: solo se listan reclamos en memoria de este proceso.")
        return list(reversed(en_memoria))
    try:
        with conexion_reclamos(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ticket, numero_pedido, motivo, detalle, thread_id, creado_en
                    FROM reclamos
                    ORDER BY creado_en DESC
                    """
                )
                registros = list(cursor.fetchall()) + en_memoria
                return sorted(
                    registros,
                    key=lambda record: datetime.fromisoformat(str(record["creado_en"])),
                    reverse=True,
                )
    except psycopg.Error:
        logger.warning("No se pudieron leer los reclamos de Postgres; se listan los de memoria.")
        return list(reversed(en_memoria))


@tool
def buscar_productos(
    consulta: str,
    categoria: str | None = None,
    marca: str | None = None,
    precio_max: int | None = None,
) -> list[dict[str, Any]] | str:
    """Busca hasta cinco productos, primero los de mejor rating.

    Cada palabra de consulta debe estar en el nombre; usa solo términos del
    producto, no frases como 'quiero' o 'hasta'. Puede ser vacía si hay filtros.
    categoria: Smartphones o Televisores. marca también se busca en el nombre.
    precio_max es un monto en pesos chilenos. Para obtener el link usa ver_producto.
    """
    return buscar_en_catalogo(consulta, categoria, marca, precio_max, limite=5)


@tool
def ver_producto(sku_id: str) -> list[dict[str, Any]] | str:
    """Obtiene el detalle y link de un producto usando su SKU."""
    return ejecutar_select(
        """
        SELECT sku_id, nombre, marca, categoria, subcategoria,
               NULLIF(BTRIM(precio_normal::text), '')::numeric AS precio_normal,
               NULLIF(BTRIM(precio_internet::text), '')::numeric AS precio_internet,
               NULLIF(BTRIM(descuento_pct::text), '')::numeric AS descuento_pct,
               NULLIF(BTRIM(rating::text), '')::numeric AS rating,
               tienda_oficial, link, imagen
        FROM catalogo.productos_unicos
        WHERE sku_id::text = %s
        """,
        (sku_id,),
    )


@tool
def mejores_ofertas(
    categoria: str | None = None,
    limite: int = 5,
) -> list[dict[str, Any]] | str:
    """Lista productos con mayor descuento, opcionalmente filtrados por categoría."""
    return ejecutar_select(
        """
        SELECT sku_id, nombre, marca,
               NULLIF(BTRIM(precio_internet::text), '')::numeric AS precio_internet,
               NULLIF(BTRIM(descuento_pct::text), '')::numeric AS descuento_pct,
               NULLIF(BTRIM(rating::text), '')::numeric AS rating, link
        FROM catalogo.productos_unicos
        WHERE NULLIF(BTRIM(descuento_pct::text), '')::numeric IS NOT NULL
          AND (%s::text IS NULL OR lower(categoria) = lower(%s::text))
        ORDER BY descuento_pct DESC NULLS LAST, rating DESC NULLS LAST
        LIMIT %s
        """,
        (categoria or None, categoria or None, max(1, limite)),
    )
