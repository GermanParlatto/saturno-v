"""Nodo `register`: alta del alumno en la posición 1.

Ojo: esto es la PRIMERA de las dos fases del alta. Aquí solo se crea la fila con el
perfil vacío. Los datos (nombre del alumno, y nombre/correo/teléfono del adulto) llegan
un turno después, en la respuesta a `R0-01`, cuando el alumno ya consta como
`registrado` y por tanto NO vuelve a pasar por este nodo. Ver el TODO de F3 en
claude/PLAN-course-engine.md.
"""

from shared.observability import logger

from ..repository import PositionConflict, create_user
from ..state import CourseState


def register(state: CourseState) -> CourseState:
    phone = state["phone"]
    try:
        creado = create_user(phone)
        return {"current_order": creado.current_order, "waiting": False, "user": creado}
    except PositionConflict:
        # Carrera: dos mensajes del mismo número entraron a la vez y otro worker ya
        # dio de alta al alumno. No es un error — se sigue con lo que haya en la tabla.
        logger.info("El alumno ya existía al registrar; se continúa con su estado")
        from ..repository import get_user_state

        existente = get_user_state(phone)
        if existente is None:  # pragma: no cover — imposible salvo borrado concurrente
            raise
        return {
            "current_order": existente.current_order,
            "waiting": existente.waiting,
            "last_node_id": existente.last_node_id,
            "user": existente,
        }
