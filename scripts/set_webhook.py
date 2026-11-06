"""Registra el webhook público del bot en Telegram."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Falta configurar {name} en el entorno o en .env.")
    return value


def main() -> None:
    token = required_setting("TELEGRAM_TOKEN")
    public_url = required_setting("PUBLIC_URL").rstrip("/")
    secret = required_setting("TELEGRAM_SECRET")
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={"url": f"{public_url}/telegram", "secret_token": secret},
        timeout=20.0,
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
