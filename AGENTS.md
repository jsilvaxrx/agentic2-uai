# Convenciones del proyecto

- Los agentes viven en `src/{nombre_agente}/` y contienen `graph.py`, `prompts.py` y `tools.py`.
- Cada nodo tiene su propio prompt en `prompts.py`. No se definen reglas ni prompts dentro de `graph.py`.
- Los agentes se ejecutan desde la raíz con `python main.py {nombre_agente} "mensaje"`.
- La flag `--saltos` imprime los nodos por los que pasó el grafo.
- La flag `--diagrama` imprime el Mermaid del grafo sin ejecutarlo.
- La API vive en `api/app.py` y se ejecuta con `uvicorn api.app:app --reload --port 8000`.
- Los scripts sueltos viven en `scripts/` y las pruebas en `tests/`, ejecutadas con `pytest`.
- Para Heroku, conservar `Procfile` con `web: uvicorn api.app:app --host 0.0.0.0 --port $PORT`, `.python-version` con `3.12` y `requirements.txt` actualizado.
