"""Esquema de estado del grafo LangGraph.

La clave está en `Annotated[list, add_messages]`:
Eso es exactamente lo que convierte una lista en un historial de conversación.
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Estado compartido por todos los nodos del grafo."""

    messages: Annotated[list, add_messages]
