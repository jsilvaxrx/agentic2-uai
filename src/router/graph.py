"""Grafo LangGraph que enruta mensajes de ecommerce."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from .catalogo import CATALOGO_NO_DISPONIBLE
from .prompts import (
    GENERICA_PROMPT,
    POSTVENTA_PROMPT,
    PREVENTA_PROMPT,
    ROUTER_PROMPT,
    ROUTER_USER_PROMPT,
)
from .tools import (
    Decision,
    buscar_productos,
    crear_reclamo,
    create_llm,
    estado_pedido,
    mejores_ofertas,
    politica,
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
        [buscar_productos, ver_producto, mejores_ofertas],
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
        conversacion = [
            message for message in messages
            if isinstance(message, HumanMessage)
            or (isinstance(message, AIMessage) and not message.tool_calls)
        ]
        if not conversacion:
            return "Sin historial previo."
        return "\n".join(
            f"{getattr(message, 'type', 'mensaje')}: {message_text(getattr(message, 'content', ''))}"
            for message in conversacion[-4:]
        )

    def router(state: RouterState) -> dict[str, Any]:
        decision = structured_llm.invoke(
            [
                SystemMessage(content=ROUTER_PROMPT),
                HumanMessage(
                    content=ROUTER_USER_PROMPT.format(
                        mensaje=state["mensaje"],
                        ruta_anterior=state.get("ruta", "ninguna"),
                        historial=history_summary(state.get("messages", [])),
                    )
                ),
            ]
        )
        return {
            "ruta": decision.ruta,
            "motivo": decision.motivo,
            "messages": [HumanMessage(content=state["mensaje"])],
            "herramientas_usadas": [],
        }

    def finalizar_preventa(state: RouterState) -> dict[str, Any]:
        # El ReAct está registrado como subgrafo real: recibe todo el historial
        # y sus nodos model/tools también quedan disponibles para el diagrama.
        messages = state.get("messages", [])
        inicio_turno = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if isinstance(messages[i], HumanMessage)),
            -1,
        )
        turno = messages[inicio_turno + 1:]
        herramientas = [message for message in turno if isinstance(message, ToolMessage)]
        final_message = next(
            (message for message in reversed(turno)
             if isinstance(message, AIMessage) and not message.tool_calls),
            None,
        )
        respuesta = message_text(final_message.content) if final_message else ""
        no_disponible = any(
            CATALOGO_NO_DISPONIBLE in message_text(message.content).lower()
            for message in herramientas
        )
        if no_disponible:
            respuesta = "Catálogo no disponible en este momento. Inténtalo nuevamente más tarde."
        if not respuesta:
            respuesta = "No pude consultar el catálogo en este momento."
        update: dict[str, Any] = {
            "respuesta": respuesta,
            "herramientas_usadas": [message.name for message in herramientas if message.name],
        }
        # El mensaje final del modelo ya está en messages; si se sustituye por
        # el aviso de indisponibilidad, reemplazarlo por ID evita duplicados.
        if final_message is None or respuesta != message_text(final_message.content):
            update["messages"] = [
                AIMessage(content=respuesta, id=final_message.id if final_message else None)
            ]
        return update

    def finalizar_postventa(state: RouterState) -> dict[str, Any]:
        messages = state.get("messages", [])
        inicio_turno = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if isinstance(messages[i], HumanMessage)),
            -1,
        )
        turno = messages[inicio_turno + 1:]
        final_message = next(
            (message for message in reversed(turno)
             if isinstance(message, AIMessage) and not message.tool_calls),
            None,
        )
        respuesta = message_text(final_message.content) if final_message else ""
        update: dict[str, Any] = {
            "herramientas_usadas": [
                message.name for message in turno
                if isinstance(message, ToolMessage) and message.name
            ],
        }
        if not respuesta:
            respuesta = "No pude revisar tu postventa en este momento."
            update["messages"] = [
                AIMessage(content=respuesta, id=final_message.id if final_message else None)
            ]
        update["respuesta"] = respuesta
        return update

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

    preventa_builder = StateGraph(RouterState)
    preventa_builder.add_node("react", preventa_agent)
    preventa_builder.add_node("finalizar_preventa", finalizar_preventa)
    preventa_builder.add_edge(START, "react")
    preventa_builder.add_edge("react", "finalizar_preventa")
    preventa_builder.add_edge("finalizar_preventa", END)

    postventa_builder = StateGraph(RouterState)
    postventa_builder.add_node("react", postventa_agent)
    postventa_builder.add_node("finalizar_postventa", finalizar_postventa)
    postventa_builder.add_edge(START, "react")
    postventa_builder.add_edge("react", "finalizar_postventa")
    postventa_builder.add_edge("finalizar_postventa", END)

    builder = StateGraph(RouterState)
    builder.add_node("router", router)
    builder.add_node("agente_preventa", preventa_builder.compile())
    builder.add_node("agente_postventa", postventa_builder.compile())
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
