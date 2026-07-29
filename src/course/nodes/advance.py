"""Nodo `advance`: persiste en `CourseStateTable` lo que el runner acaba de decidir.

Todo lo que escribe estado vive aquí, después del envío. El avance es CONDICIONAL
(`current_order = :expected`): si otra invocación ya movió al alumno, esta pierde la
carrera y para, en vez de adelantar la posición dos veces.
"""

import os

from shared.observability import logger

from ..continuation import enqueue_continuation
from ..repository import PositionConflict, advance_position, set_waiting
from ..state import CourseState


def _max_nodes() -> int:
    return int(os.environ.get("MAX_NODES_PER_INVOCATION", "10"))


def advance(state: CourseState) -> CourseState:
    phone = state["phone"]

    if state.get("course_completed"):
        return {}

    if state.get("waiting"):
        # Pausa: la posición NO avanza; el nodo actual sigue siendo el pendiente de
        # respuesta. Solo se marca la espera para que el próximo mensaje lo sepa.
        set_waiting(phone, True)
        return {}

    order = state["current_order"]
    try:
        advance_position(
            phone,
            expected_order=order,
            next_order=order + 1,
            last_node_id=state.get("last_node_id") or "",
        )
    except PositionConflict:
        # Otra invocación ya avanzó desde esta misma posición: el mensaje que acabamos
        # de enviar era un duplicado. Se corta aquí para no encadenar más duplicados.
        logger.info("Avance descartado: la posición ya había cambiado")
        return {"continue_flag": False}

    siguiente = order + 1

    if state.get("sent_count", 0) >= _max_nodes():
        # Tope de la invocación. La posición ya está persistida, así que la continuación
        # retoma exactamente aquí. Se corta el loop ANTES de agotar el Timeout de 120s.
        logger.info("Tope de nodos por invocación; se re-encola la continuación")
        enqueue_continuation(phone, state["phone_number_id"])
        return {"current_order": siguiente, "throttled": True, "continue_flag": False}

    return {"current_order": siguiente}
