"""Grafo LangGraph que enruta mensajes de ecommerce."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .prompts import GENERICA_PROMPT, POSTVENTA_PROMPT, PREVENTA_PROMPT, ROUTER_PROMPT
from .tools import Decision, create_llm

load_dotenv()


class RouterState(TypedDict, total=False):
    mensaje: str
    ruta: Literal["preventa", "postventa", "generica"]
    motivo: str
    respuesta: str
    messages: Annotated[list[Any], add_messages]


def create_graph(llm: Any | None = None):
    """Compila el router, con memoria aislada por `thread_id`."""
    structured_llm = (llm or create_llm()).with_structured_output(Decision)

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
        respuesta = "Hola, este chat está para ayudarte con consultas de nuestra tienda."
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
    return builder.compile(checkpointer=MemorySaver())
