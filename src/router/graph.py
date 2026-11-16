"""Grafo LangGraph que enruta mensajes de ecommerce."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .prompts import GENERICA_PROMPT, POSTVENTA_PROMPT, PREVENTA_PROMPT, ROUTER_PROMPT
from .tools import (
    Decision,
    buscar_productos,
    consultar_redes,
    crear_reclamo,
    create_llm,
    estado_pedido,
    etiqueta_herramienta,
    mejores_ofertas,
    politica,
    reset_reclamo_thread_id,
    set_reclamo_thread_id,
    ver_producto,
)

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
    herramientas_usadas: list[str]
    messages: Annotated[list[Any], add_messages]


def create_graph(llm: Any | None = None, checkpointer: Any | None = None):
    """Compila el router, con memoria aislada por `thread_id`."""
    model = llm or create_llm()
    structured_llm = model.with_structured_output(Decision)
    preventa_agent = create_agent(
        model,
        [buscar_productos, ver_producto, mejores_ofertas, consultar_redes],
        system_prompt=PREVENTA_PROMPT,
    )
    postventa_agent = create_agent(
        model,
        [estado_pedido, politica, crear_reclamo],
        system_prompt=POSTVENTA_PROMPT,
    )

    def message_text(content: Any) -> str:
        if isinstance(content, list):
            return "".join(
                str(block.get("text", "")) if isinstance(block, dict) else str(block)
                for block in content
            ).strip()
        return str(content).strip()

    def history_summary(messages: list[Any]) -> str:
        if not messages:
            return "Sin historial previo."
        return "\n".join(
            f"{getattr(message, 'type', 'mensaje')}: {message_text(getattr(message, 'content', ''))}"
            for message in messages[-4:]
        )

    def router(state: RouterState) -> dict[str, Any]:
        decision = structured_llm.invoke(
            ROUTER_PROMPT.format(
                mensaje=state["mensaje"],
                ruta_anterior=state.get("ruta", "ninguna"),
                historial=history_summary(state.get("messages", [])),
            )
        )
        return {
            "ruta": decision.ruta,
            "motivo": decision.motivo,
            "messages": [HumanMessage(content=state["mensaje"])],
        }

    def agente_preventa(state: RouterState, config: RunnableConfig) -> dict[str, Any]:
        herramientas_usadas: list[str] = []
        final_message: AIMessage | None = None
        thread_id = str(config.get("configurable", {}).get("thread_id", "sin-hilo"))
        token = set_reclamo_thread_id(thread_id)
        try:
            for event in preventa_agent.stream(
                {"messages": state.get("messages", [])}, stream_mode="updates"
            ):
                for node_name, update in event.items():
                    if node_name == "tools":
                        for message in update.get("messages", []):
                            if getattr(message, "name", None):
                                herramientas_usadas.append(etiqueta_herramienta(message.name))
                    if node_name == "model":
                        for message in update.get("messages", []):
                            if isinstance(message, AIMessage) and message.content:
                                final_message = message
        finally:
            reset_reclamo_thread_id(token)

        respuesta = message_text(final_message.content if final_message else "")
        if not respuesta:
            respuesta = "No pude consultar el catálogo en este momento."
        return {
            "respuesta": respuesta,
            "messages": [AIMessage(content=respuesta)],
            "herramientas_usadas": herramientas_usadas,
        }

    def agente_postventa(state: RouterState, config: RunnableConfig) -> dict[str, Any]:
        herramientas_usadas: list[str] = []
        final_message: AIMessage | None = None
        thread_id = str(config.get("configurable", {}).get("thread_id", "sin-hilo"))
        token = set_reclamo_thread_id(thread_id)
        try:
            for event in postventa_agent.stream(
                {"messages": state.get("messages", [])}, stream_mode="updates"
            ):
                for node_name, update in event.items():
                    if node_name == "tools":
                        for message in update.get("messages", []):
                            if getattr(message, "name", None):
                                herramientas_usadas.append(etiqueta_herramienta(message.name))
                    if node_name == "model":
                        for message in update.get("messages", []):
                            if isinstance(message, AIMessage) and message.content:
                                final_message = message
        finally:
            reset_reclamo_thread_id(token)

        respuesta = message_text(final_message.content if final_message else "")
        if not respuesta:
            respuesta = "No pude revisar tu postventa en este momento."
        return {
            "respuesta": respuesta,
            "messages": [AIMessage(content=respuesta)],
            "herramientas_usadas": herramientas_usadas,
        }

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
            respuesta = message_text(model_response.content)
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
