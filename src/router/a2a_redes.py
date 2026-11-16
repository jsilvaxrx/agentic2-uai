"""Cliente A2A para consultar al agente de redes sociales del curso."""

from __future__ import annotations

import os

from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageRequest
import httpx

TIMEOUT_SEGUNDOS = 60.0


async def preguntar_redes(texto: str, hilo: str) -> str:
    """Envía `texto` al agente de redes dentro del contexto `hilo` y devuelve su respuesta."""
    intel_url = os.getenv("INTEL_URL")
    intel_token = os.getenv("INTEL_TOKEN")
    if not intel_url or not intel_token:
        raise RuntimeError("INTEL_URL e INTEL_TOKEN deben estar configuradas.")

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {intel_token}"},
        timeout=TIMEOUT_SEGUNDOS,
    ) as http:
        client = await create_client(
            intel_url,
            client_config=ClientConfig(httpx_client=http, streaming=False),
        )
        partes: list[str] = []
        async for response in client.send_message(
            SendMessageRequest(
                message=new_text_message(texto, role=Role.ROLE_USER, context_id=hilo)
            )
        ):
            parte = get_stream_response_text(response).strip()
            if parte and parte not in partes:
                partes.append(parte)
    return "\n".join(partes)
