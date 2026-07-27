"""Nodo SUPERVISOR: enruta al agente adecuado y agrega resultados.

Con el LLM decide la siguiente acción: 'rag' | 'pedidos' | 'handoff' | 'fin'.
Es el origen de las aristas condicionales del grafo.
"""

from agents.state import AgentState


def supervisor_node(state: AgentState) -> dict:
    # TODO: prompt de routing -> pedir al LLM que elija el siguiente agente.
    # TODO: devolver {"route": "<rag|pedidos|handoff|fin>"}
    raise NotImplementedError("Implementar router del supervisor")


def route(state: AgentState) -> str:
    """Función de arista condicional: mapea state['route'] al nodo destino."""
    # TODO: return state["route"]
    raise NotImplementedError("Implementar mapeo de aristas condicionales")
