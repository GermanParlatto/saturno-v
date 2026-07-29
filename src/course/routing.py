"""Routing del grafo del curso: `if/else` de Python, sin LLM (§7 del documento).

La ruta del curso es LINEAL: `route_sequence` nunca elige a qué nodo ir, solo decide
continuar, pausar o terminar. El nodo siguiente siempre es `current_order + 1`.
"""

from .state import CourseState


def route_by_status(state: CourseState) -> str:
    """Alumno nuevo -> alta; alumno conocido -> retomar donde lo dejó."""
    return "register" if state.get("status") == "nuevo" else "check_progress"


def route_sequence(state: CourseState) -> str:
    """Decide si seguir el loop, pausar o terminar la invocación.

    El orden de las comprobaciones importa: `course_completed` y `waiting` son estados
    terminales de la invocación y se evalúan antes que `continue_flag`.
    """
    if state.get("course_completed"):
        return "end"
    if state.get("waiting"):
        return "end"  # pausa: se reanuda cuando el alumno responda
    if state.get("throttled"):
        return "end"  # tope de la invocación: la continuación ya está re-encolada
    return "sequence_runner" if state.get("continue_flag") else "end"
