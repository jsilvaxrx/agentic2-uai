"""Acceso de solo lectura al catálogo compartido con la memoria del router."""

from __future__ import annotations

import os
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row


CATALOGO_NO_DISPONIBLE = "catálogo no disponible"


def ejecutar_select(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]] | str:
    """Ejecuta un SELECT parametrizado y cierra la conexión al terminar."""
    if not sql.lstrip().upper().startswith("SELECT") or ";" in sql:
        raise ValueError("Solo se permiten consultas SELECT de una sola sentencia.")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return CATALOGO_NO_DISPONIBLE

    try:
        with psycopg.connect(
            database_url,
            connect_timeout=5,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
    except Exception as e:
        print(f"Error al ejecutar consulta: {e}")
        return CATALOGO_NO_DISPONIBLE


def buscar_en_catalogo(
    consulta: str,
    categoria: str | None = None,
    marca: str | None = None,
    precio_max: int | None = None,
    limite: int = 5,
) -> list[dict[str, Any]] | str:
    """Busca productos aplicando filtros fijos y valores siempre parametrizados."""
    conditions: list[str] = []
    params: list[Any] = []

    for palabra in consulta.split():
        conditions.append("nombre ILIKE %s")
        params.append(f"%{palabra}%")
    if categoria:
        conditions.append("categoria ILIKE %s")
        params.append(categoria)
    if marca:
        conditions.append("(marca ILIKE %s OR nombre ILIKE %s)")
        params.extend((f"%{marca}%", f"%{marca}%"))
    if precio_max is not None:
        conditions.append("precio_internet <= %s")
        params.append(precio_max)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT sku_id, nombre, marca, precio_internet, descuento_pct, rating
        FROM catalogo.productos_unicos
        {where}
        ORDER BY rating DESC NULLS LAST
        LIMIT %s
    """
    params.append(max(1, min(limite, 10)))
    return ejecutar_select(sql, params)
