"""Punto de entrada para ejecutar un agente LangGraph."""

from __future__ import annotations

import argparse
import importlib
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta un agente del proyecto.")
    parser.add_argument("agente", help="Nombre del directorio del agente en src/.")
    parser.add_argument("mensaje", help="Mensaje de entrada para el agente.")
    parser.add_argument("--saltos", action="store_true", help="Imprime los nodos recorridos.")
    parser.add_argument("--diagrama", action="store_true", help="Imprime el Mermaid sin ejecutar.")
    parser.add_argument(
        "--thread-id",
        default="cli",
        help="Identificador de la conversación para la memoria del grafo.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        module = importlib.import_module(f"src.{args.agente}.graph")
        graph = module.create_graph()
    except (ImportError, AttributeError) as error:
        sys.exit(f"No se pudo cargar el agente '{args.agente}': {error}")

    if args.diagrama:
        print(graph.get_graph().draw_mermaid())
        return

    if args.saltos:
        config = {"configurable": {"thread_id": args.thread_id}}
        for event in graph.stream(
            {"mensaje": args.mensaje}, config=config, stream_mode="updates"
        ):
            node, update = next(iter(event.items()))
            print(f"Nodo: {node}")
            if node == "router" and "motivo" in update:
                print(f"Motivo: {update['motivo']}")
        return

    result = graph.invoke(
        {"mensaje": args.mensaje},
        config={"configurable": {"thread_id": args.thread_id}},
    )
    print(result)


if __name__ == "__main__":
    main()
