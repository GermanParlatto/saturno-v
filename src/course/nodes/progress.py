"""Nodo `check_progress`: evalúa la respuesta del alumno y decide si el curso avanza.

Es el punto donde el curso sale de una pausa. La decisión de avanzar NO es del alumno
por el mero hecho de contestar: la toma `evaluate.py` según el `eval_type` del nodo.
Un ejercicio `strict` sin resolver mantiene la posición y escala pistas.
"""

from shared.kapso_client import send_text
from shared.observability import logger
from shared.whatsapp_format import format_for_whatsapp

from ..catalog import get_node
from ..repository import PositionConflict, advance_position, get_user_state, reset_attempts
from ..state import CourseState
from .evaluate import evaluar


def check_progress(state: CourseState) -> CourseState:
    phone = state["phone"]
    order = state["current_order"]

    if not state.get("waiting"):
        # El alumno escribió sin que hubiera pregunta pendiente (p. ej. a mitad de una
        # cadena que se re-encoló). No hay respuesta que consumir: se sigue desde donde
        # esté, sin avanzar, para no saltarse un nodo.
        return {"continue_flag": True}

    nodo = get_node(state["last_node_id"]) if state.get("last_node_id") else None
    if nodo is None:
        # Estado inconsistente (nodo retirado del catálogo entre dos mensajes): se
        # avanza para no dejar al alumno atascado en una pausa sin nodo.
        logger.warning(
            "Pausa sin nodo en el catálogo",
            extra={"last_node_id": state.get("last_node_id")},
        )
        return _avanzar(state, phone, order)

    mensaje, avanza = evaluar(nodo, state.get("student_answer", ""), get_user_state(phone), phone)

    enviados = state.get("sent_count", 0)
    if mensaje and mensaje.strip():
        send_text(state["phone_number_id"], to=phone, body=format_for_whatsapp(mensaje))
        enviados += 1

    if not avanza:
        # Sigue pendiente del mismo nodo: la posición no se mueve y la invocación
        # termina aquí (route_sequence ve waiting=True).
        return {"waiting": True, "continue_flag": False, "sent_count": enviados}

    resultado = _avanzar(state, phone, order)
    resultado["sent_count"] = enviados
    return resultado


def _avanzar(state: CourseState, phone: str, order: int) -> CourseState:
    """Consume la pausa: avanza la posición y reinicia el contador de intentos."""
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

    reset_attempts(phone)
    return {"current_order": order + 1, "waiting": False, "continue_flag": True}
