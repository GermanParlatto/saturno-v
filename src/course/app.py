"""Entrypoint del motor de curso: la única función que el worker necesita conocer.

A diferencia de `agents.app.run_graph`, esto NO devuelve texto para que el llamador lo
envíe: el grafo envía por Kapso a medida que recorre nodos (una invocación puede producir
varios mensajes, o ninguno). El worker solo dispara y observa.
"""

import os

from .graph import build_course_graph
from .state import CourseState

# Se construye UNA VEZ por contenedor Lambda, igual que el grafo legacy.
GRAPH = build_course_graph()


def _recursion_limit() -> int:
    # Cada nodo del curso consume DOS pasos del grafo (runner + advance), más los de
    # entrada. El límite por defecto de LangGraph (25) cortaría la cadena antes que
    # nuestra propia guarda, y encima con excepción en vez de con re-encolado.
    return 2 * int(os.environ.get("MAX_NODES_PER_INVOCATION", "10")) + 10


def run_course(phone: str, text: str, phone_number_id: str) -> CourseState:
    """Avanza el curso para un alumno. Devuelve el estado final (útil en tests y trazas)."""
    return GRAPH.invoke(
        {
            "phone": phone,
            "phone_number_id": phone_number_id,
            "student_answer": text,
            "sent_count": 0,
        },
        {"recursion_limit": _recursion_limit()},
    )
