"""Nodo `check_progress`: consume la respuesta del alumno y reanuda la secuencia.

Es el punto donde el curso sale de una pausa. En F3 **cualquier respuesta avanza**: la
evaluación (feedback socrático, escalada de pistas, extracción del perfil de `R0-01`)
llega en F4 y se enchufa aquí, entre consumir la respuesta y avanzar.
"""

from shared.observability import logger

from ..catalog import get_node
from ..repository import PositionConflict, advance_position, get_user_state
from ..state import CourseState


def check_progress(state: CourseState) -> CourseState:
    phone = state["phone"]
    order = state["current_order"]

    if not state.get("waiting"):
        # El alumno escribió sin que hubiera pregunta pendiente (p. ej. a mitad de una
        # cadena que se re-encoló). No hay respuesta que consumir: se sigue desde donde
        # esté, sin avanzar, para no saltarse un nodo.
        return {"continue_flag": True}

    nodo = get_node(state["last_node_id"]) if state.get("last_node_id") else None

    if nodo is not None and nodo.eval_type == "register":
        # TODO F4: extraer student_name / adult_name / adult_email / adult_phone de la
        # respuesta y persistirlos con el LLM. Hasta entonces el perfil queda vacío y el
        # alumno avanza igual: R0-01 es el nodo 1 y bloquear aquí dejaría el curso muerto.
        logger.warning(
            "Respuesta de registro sin extracción de perfil (pendiente de F4)",
            extra={"node_id": nodo.node_id},
        )

    try:
        advance_position(
            phone,
            expected_order=order,
            next_order=order + 1,
            last_node_id=state.get("last_node_id") or "",
        )
    except PositionConflict:
        # Reentrega tardía de SQS: otra invocación ya consumió esta respuesta. Se
        # recarga la posición real y se continúa desde ahí, sin reenviar nada.
        logger.info("La posición ya había avanzado; se retoma el estado actual")
        actual = get_user_state(phone)
        if actual is None:  # pragma: no cover — solo si se borró el alumno en medio
            return {"course_completed": True, "continue_flag": False}
        return {
            "current_order": actual.current_order,
            "waiting": actual.waiting,
            "continue_flag": not actual.waiting,
        }

    return {"current_order": order + 1, "waiting": False, "continue_flag": True}
