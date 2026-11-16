from __future__ import annotations

from src.router import tools


def test_consultar_redes_recorta_la_respuesta(monkeypatch) -> None:
    recibido: dict[str, str] = {}

    async def fake_preguntar(texto: str, hilo: str) -> str:
        recibido.update(texto=texto, hilo=hilo)
        return "x" * 5000

    monkeypatch.setattr(tools, "preguntar_redes", fake_preguntar)
    token = tools.set_reclamo_thread_id("hilo-1")
    try:
        respuesta = tools.consultar_redes.invoke({"tema": "marca Acme"})
    finally:
        tools.reset_reclamo_thread_id(token)

    assert respuesta == "x" * tools.REDES_MAX_CARACTERES
    assert recibido == {"texto": "marca Acme", "hilo": "hilo-1"}


def test_consultar_redes_no_se_cae_si_el_agente_falla(monkeypatch) -> None:
    async def fake_preguntar(texto: str, hilo: str) -> str:
        raise TimeoutError("sin respuesta")

    monkeypatch.setattr(tools, "preguntar_redes", fake_preguntar)

    assert tools.consultar_redes.invoke({"tema": "marca Acme"}) == tools.REDES_NO_DISPONIBLE
