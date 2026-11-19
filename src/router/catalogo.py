"""Acceso de solo lectura al catálogo compartido con la memoria del router."""

from __future__ import annotations

import logging
import os
import re
from threading import BoundedSemaphore
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row


CATALOGO_NO_DISPONIBLE = "catálogo no disponible"
logger = logging.getLogger(__name__)
# El checkpointer usa hasta dos conexiones. El catálogo usa solo una a la vez,
# incluso cuando ReAct lanza varias herramientas en paralelo, y la cierra siempre.
_CONEXION_CATALOGO = BoundedSemaphore(1)


def ejecutar_select(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]] | str:
    """Ejecuta un SELECT parametrizado y cierra la conexión al terminar."""
    if not re.match(r"\s*SELECT\b", sql, re.IGNORECASE) or ";" in sql:
        raise ValueError("Solo se permiten consultas SELECT de una sola sentencia.")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return CATALOGO_NO_DISPONIBLE

    if not _CONEXION_CATALOGO.acquire(timeout=5):
        return CATALOGO_NO_DISPONIBLE
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
    except psycopg.Error:
        logger.warning("El catálogo no está disponible.")
        return CATALOGO_NO_DISPONIBLE
    finally:
        _CONEXION_CATALOGO.release()


def buscar_en_catalogo(
    consulta: str,
    categoria: str | None = None,
    marca: str | None = None,
    precio_max: int | None = None,
    limite: int = 5,
) -> list[dict[str, Any]] | str:
    """Busca productos aplicando filtros fijos y valores siempre parametrizados."""
    sql = """
        SELECT sku_id, nombre, marca,
               NULLIF(BTRIM(precio_internet::text), '')::numeric AS precio_internet,
               NULLIF(BTRIM(descuento_pct::text), '')::numeric AS descuento_pct,
               NULLIF(BTRIM(rating::text), '')::numeric AS rating
        FROM catalogo.productos_unicos
        WHERE NOT EXISTS (
            SELECT 1 FROM unnest(%s::text[]) AS term(palabra)
            WHERE strpos(lower(COALESCE(nombre, '')), lower(term.palabra)) = 0
        )
          AND (%s::text IS NULL OR lower(categoria) = lower(%s::text))
          AND (%s::text IS NULL
               OR strpos(lower(COALESCE(marca, '')), lower(%s::text)) > 0
               OR strpos(lower(COALESCE(nombre, '')), lower(%s::text)) > 0)
          AND (%s::numeric IS NULL
               OR NULLIF(BTRIM(precio_internet::text), '')::numeric <= %s::numeric)
        ORDER BY rating DESC NULLS LAST
        LIMIT %s
    """
    params = (
        consulta.split(), categoria or None, categoria or None,
        marca or None, marca or None, marca or None,
        precio_max, precio_max, max(1, min(limite, 10)),
    )
    return ejecutar_select(sql, params)
