"""Grafo LangGraph que enruta mensajes de ecommerce."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .prompts import GENERICA_PROMPT, POSTVENTA_PROMPT, PREVENTA_PROMPT, ROUTER_PROMPT
from .tools import Decision, create_llm

load_dotenv()
TIENDA_CONTEXT = (Path(__file__).resolve().parents[2] / "data" / "tienda.md").read_text(
    encoding="utf-8"
)
GENERICA_FALLBACK = "Hola, este chat está para ayudarte con consultas de nuestra tienda."


class RouterState(TypedDict, total=False):
    mensaje: str
    ruta: Literal["preventa", "postventa", "generica"]
    motivo: str
    respuesta: str
    messages: Annotated[list[Any], add_messages]


def create_graph(llm: Any | None = None, checkpointer: Any | None = None):
    """Compila el router, con memoria aislada por `thread_id`."""
    model = llm or create_llm()
    structured_llm = model.with_structured_output(Decision)

    def router(state: RouterState) -> dict[str, Any]:
        decision = structured_llm.invoke(ROUTER_PROMPT.format(mensaje=state["mensaje"]))
        return {
            "ruta": decision.ruta,
            "motivo": decision.motivo,
            "messages": [HumanMessage(content=state["mensaje"])],
        }

    def agente_preventa(state: RouterState) -> dict[str, Any]:
        respuesta = (
            f"Soy el agente de preventa. Recibí: {state['mensaje']}. "
            "Pronto podré ayudarte con productos y compras."
        )
        return {"respuesta": respuesta, "messages": [AIMessage(content=respuesta)]}

    def agente_postventa(state: RouterState) -> dict[str, Any]:
        respuesta = (
            f"Soy el agente de postventa. Recibí: {state['mensaje']}. "
            "Pronto podré ayudarte con tu pedido."
        )
        return {"respuesta": respuesta, "messages": [AIMessage(content=respuesta)]}

    def respuesta_generica(state: RouterState) -> dict[str, Any]:
        try:
            model_response = model.invoke(
                [
                    SystemMessage(
                        content=GENERICA_PROMPT.format(tienda_context=TIENDA_CONTEXT)
                    ),
                    *state.get("messages", []),
                ]
            )
            respuesta = str(model_response.content).strip()
            if not respuesta:
                raise ValueError("El modelo devolvió una respuesta vacía.")
        except Exception:
            respuesta = GENERICA_FALLBACK
        return {"respuesta": respuesta, "messages": [AIMessage(content=respuesta)]}

    def select_route(state: RouterState) -> str:
        return state["ruta"]

    builder = StateGraph(RouterState)
    builder.add_node("router", router)
    builder.add_node("agente_preventa", agente_preventa)
    builder.add_node("agente_postventa", agente_postventa)
    builder.add_node("respuesta_generica", respuesta_generica)
    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        select_route,
        {
            "preventa": "agente_preventa",
            "postventa": "agente_postventa",
            "generica": "respuesta_generica",
        },
    )
    builder.add_edge("agente_preventa", END)
    builder.add_edge("agente_postventa", END)
    builder.add_edge("respuesta_generica", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())
