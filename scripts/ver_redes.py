"""Pregunta directo al agente de redes por A2A e imprime su respuesta completa."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.router.a2a_redes import preguntar_redes


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta al agente de redes sociales.")
    parser.add_argument("pregunta", help="Pregunta para el agente de redes.")
    parser.add_argument(
        "--hilo",
        default=f"cli-{uuid4().hex[:8]}",
        help="Identificador de la conversación en el agente de redes.",
    )
    args = parser.parse_args()

    try:
        respuesta = asyncio.run(preguntar_redes(args.pregunta, args.hilo))
    except Exception as error:
        sys.exit(f"El agente de redes no respondió ({type(error).__name__}): {error}")
    print(respuesta or "El agente de redes respondió sin texto.")


if __name__ == "__main__":
    main()
