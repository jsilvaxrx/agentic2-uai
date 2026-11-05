"""Prueba de integración del router contra los casos de evaluación."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.router.graph import create_graph


CASES_PATH = Path(__file__).with_name("casos_router.json")
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="Requiere GOOGLE_API_KEY para evaluar el router con Gemini.",
)
@pytest.mark.parametrize("cases", [CASES], ids=["casos_router"])
def test_router_has_at_least_thirteen_correct_routes(cases: list[dict[str, str]]) -> None:
    graph = create_graph()
    correct = 0

    for index, case in enumerate(cases, start=1):
        result = graph.invoke(
            {"mensaje": case["mensaje"]},
            config={"configurable": {"thread_id": f"pytest-router-{index}"}},
        )
        correct += result["ruta"] == case["esperado"]

    assert correct >= 13, f"El router acertó {correct}/15 casos; se requieren al menos 13."
