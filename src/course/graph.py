"""Ensamblado del grafo del curso.

    START → identify_user → ┬→ register       ─┐
                            └→ check_progress ─┤
                                               ▼
                                        sequence_runner → advance ─┐
                                               ▲                   │
                                               └───────────────────┘
                                                (route_sequence)   → END

**Sin checkpointer**, al contrario que `agents/graph.py`: `CourseStateTable` ya es la
fuente de verdad de la posición y añadir `DynamoDBSaver` encima crearía dos stores que
pueden divergir. El estado se carga en `identify_user` y se escribe en `advance`.
"""

from langgraph.graph import END, START, StateGraph

from .nodes.advance import advance
from .nodes.identify import identify_user
from .nodes.progress import check_progress
from .nodes.register import register
from .nodes.runner import sequence_runner
from .routing import route_by_status, route_sequence
from .state import CourseState


def build_course_graph():
    g = StateGraph(CourseState)

    g.add_node("identify_user", identify_user)
    g.add_node("register", register)
    g.add_node("check_progress", check_progress)
    g.add_node("sequence_runner", sequence_runner)
    g.add_node("advance", advance)

    g.add_edge(START, "identify_user")
    g.add_conditional_edges(
        "identify_user",
        route_by_status,
        {"register": "register", "check_progress": "check_progress"},
    )
    g.add_edge("register", "sequence_runner")

    # check_progress puede terminar el curso (respuesta al último nodo) sin llegar a
    # enviar nada, así que también pasa por el routing en vez de ir directo al runner.
    g.add_conditional_edges(
        "check_progress",
        route_sequence,
        {"sequence_runner": "sequence_runner", "end": END},
    )

    # El runner NUNCA escribe: siempre pasa por advance, que persiste y decide si el
    # loop sigue. Así hay un solo sitio donde el estado toca DynamoDB.
    g.add_edge("sequence_runner", "advance")
    g.add_conditional_edges(
        "advance",
        route_sequence,
        {"sequence_runner": "sequence_runner", "end": END},
    )

    return g.compile()
