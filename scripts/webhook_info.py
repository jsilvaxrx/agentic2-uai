"""Muestra el estado actual y errores pendientes del webhook de Telegram."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        sys.exit("Falta configurar TELEGRAM_TOKEN en el entorno o en .env.")

    response = httpx.get(
        f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=20.0
    )
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"status_code": response.status_code, "body": response.text}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    response.raise_for_status()
    if not payload.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
