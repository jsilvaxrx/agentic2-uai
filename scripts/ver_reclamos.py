"""Lista los reclamos persistidos de postventa."""

from __future__ import annotations

from pathlib import Path
import sys
import logging

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.router.tools import listar_reclamos


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    reclamos = listar_reclamos()
    if not reclamos:
        print("No hay reclamos guardados.")
        return
    for reclamo in reclamos:
        print(
            f"{reclamo['ticket']} | pedido {reclamo['numero_pedido']} | "
            f"{reclamo['motivo']} | hilo {reclamo['thread_id']} | {reclamo['creado_en']}"
        )
        print(f"  Detalle: {reclamo['detalle']}")


if __name__ == "__main__":
    main()
