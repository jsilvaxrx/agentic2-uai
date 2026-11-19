"""Consulta rápida de la vista de catálogo desde la terminal."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.router.catalogo import CATALOGO_NO_DISPONIBLE, ejecutar_select


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta productos del catálogo.")
    parser.add_argument("texto", nargs="?", help="Texto que debe aparecer en el nombre.")
    args = parser.parse_args()

    if args.texto is not None:
        products = ejecutar_select(
            """
            SELECT sku_id, nombre,
                   NULLIF(BTRIM(precio_internet::text), '')::numeric AS precio_internet,
                   NULLIF(BTRIM(rating::text), '')::numeric AS rating
            FROM catalogo.productos_unicos
            WHERE strpos(lower(nombre), lower(%s::text)) > 0
            ORDER BY rating DESC NULLS LAST
            LIMIT 10
            """,
            (args.texto,),
        )
        if products == CATALOGO_NO_DISPONIBLE:
            print(CATALOGO_NO_DISPONIBLE)
            return
        if not products:
            print("No se encontraron productos.")
        for product in products:
            precio = f"${product['precio_internet']:,.0f}".replace(",", ".")
            rating = product["rating"] if product["rating"] is not None else "sin dato"
            print(
                f"{product['sku_id']} | {product['nombre']} | "
                f"{precio} | rating: {rating}"
            )
        return

    categories = ejecutar_select(
        """
        SELECT categoria, COUNT(*) AS productos
        FROM catalogo.productos_unicos
        GROUP BY categoria
        ORDER BY categoria
        """
    )
    if categories == CATALOGO_NO_DISPONIBLE:
        print(CATALOGO_NO_DISPONIBLE)
        return
    for category in categories:
        print(f"{category['categoria']}: {category['productos']}")


if __name__ == "__main__":
    main()
