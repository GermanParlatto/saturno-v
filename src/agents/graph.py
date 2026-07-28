"""Construcción del grafo.

(ahora):     START -> llm -> finalizer -> END
proximante: START -> supervisor -> { rag | OCR | save prompt } -> supervisor -> finalizer -> END

"""

from langgraph.graph import END, START, StateGraph

from agents.memory import get_checkpointer
from agents.nodes.finalizer import finalizer
from agents.nodes.llm import llm_node
from agents.state import AgentState


def build_graph():
    """Ensambla y compila el grafo con memoria persistente."""
    g = StateGraph(AgentState)

    g.add_node("llm", llm_node)
    g.add_node("finalizer", finalizer)
    g.add_edge(START, "llm")
    g.add_edge("llm", "finalizer")
    g.add_edge("finalizer", END)

    return g.compile(checkpointer=get_checkpointer())
