"""Consulta rápida de la vista de catálogo desde la terminal."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.router.catalogo import CATALOGO_NO_DISPONIBLE, buscar_en_catalogo, ejecutar_select


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta productos del catálogo.")
    parser.add_argument("texto", nargs="?", help="Texto que debe aparecer en el nombre.")
    args = parser.parse_args()

    if args.texto:
        products = buscar_en_catalogo(args.texto, limite=10)
        if products == CATALOGO_NO_DISPONIBLE:
            print(CATALOGO_NO_DISPONIBLE)
            return
        for product in products:
            print(
                f"{product['sku_id']} | {product['nombre']} | "
                f"${product['precio_internet']:,} | rating: {product['rating'] or 'sin dato'}"
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
