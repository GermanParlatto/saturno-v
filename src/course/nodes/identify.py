"""Nodo `identify_user`: carga el estado del alumno desde `CourseStateTable`.

Es la puerta de entrada del grafo y el punto donde se lee la ÚNICA fuente de verdad de
la posición. Todo lo que venga después trabaja sobre el espejo en memoria.
"""

from ..repository import get_user_state
from ..state import CourseState


def identify_user(state: CourseState) -> CourseState:
    phone = state["phone"]
    guardado = get_user_state(phone)

    if guardado is None:
        # Cualquier mensaje de un número desconocido arranca el curso (asunción 3 de
        # §7 del plan). No hay más señal de onboarding que el primer mensaje.
        return {
            "status": "nuevo",
            "current_order": 0,
            "waiting": False,
            "sent_count": 0,
            "user": None,
        }

    return {
        "status": "registrado",
        "current_order": guardado.current_order,
        "last_node_id": guardado.last_node_id,
        "waiting": guardado.waiting,
        "sent_count": 0,
        "user": guardado,
    }
