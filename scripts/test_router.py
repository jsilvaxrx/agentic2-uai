"""Evalúa el enrutamiento de Gemini contra los casos definidos en tests/."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.router.graph import create_graph


def load_cases() -> list[dict[str, str]]:
    cases_path = PROJECT_ROOT / "tests" / "casos_router.json"
    return json.loads(cases_path.read_text(encoding="utf-8"))


def main() -> None:
    graph = create_graph()
    cases = load_cases()
    results: list[dict[str, str | bool]] = []

    print(f"{'Mensaje':<52} {'Esperado':<11} {'Obtenido':<11} Estado  Motivo")
    print("-" * 125)
    for index, case in enumerate(cases, start=1):
        result = graph.invoke(
            {"mensaje": case["mensaje"]},
            config={"configurable": {"thread_id": f"router-eval-{index}"}},
        )
        obtained = result["ruta"]
        passed = obtained == case["esperado"]
        results.append(
            {
                "mensaje": case["mensaje"],
                "esperado": case["esperado"],
                "obtenido": obtained,
                "motivo": result["motivo"],
                "passed": passed,
            }
        )
        status = "✔" if passed else "✘"
        print(
            f"{case['mensaje'][:50]:<52} {case['esperado']:<11} {obtained:<11} "
            f"{status:<7} {result['motivo']}"
        )

    correct = sum(result["passed"] for result in results)
    total = len(results)
    print(f"\nAciertos: {correct}/{total} ({correct / total:.0%})")

    failures = [result for result in results if not result["passed"]]
    if failures:
        print("Fallados:")
        for result in failures:
            print(
                f"- {result['mensaje']} | esperado: {result['esperado']} | "
                f"obtenido: {result['obtenido']}"
            )
    else:
        print("Fallados: ninguno")


if __name__ == "__main__":
    main()
