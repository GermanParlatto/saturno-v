"""Estado del grafo del curso (§8 del documento v2, adaptado).

Este `TypedDict` es estado **de la invocación**, no la fuente de verdad: la posición del
alumno vive en `CourseStateTable` y se carga en `identify_user`. Por eso el grafo no usa
checkpointer de LangGraph — dos stores que puedan divergir serían un bug esperando a
ocurrir (ver §3 de claude/PLAN-course-engine.md).

Diferencias con §8 del documento:

- `phone_number_id`: necesario para enviar por Kapso; el documento no lo contempla.
- `sent_count`: mensajes enviados en ESTA invocación. Sostiene la guarda contra la ráfaga
  de 7 nodos `pauses=false` seguidos.
- `throttled`: se alcanzó `MAX_NODES_PER_INVOCATION` y la continuación quedó re-encolada.
- `messages`: NO se incluye. El grafo no acumula historial: cada invocación arranca del
  estado en DynamoDB. El historial conversacional entra en F4, si el evaluador lo necesita.
"""

from typing import TypedDict


class CourseState(TypedDict, total=False):
    # identidad
    phone: str
    phone_number_id: str
    status: str  # "nuevo" | "registrado"
    # posición (espejo de CourseStateTable durante la invocación)
    current_order: int
    last_node_id: str | None
    waiting: bool
    # entrada del alumno
    student_answer: str
    # control del loop
    course_completed: bool
    continue_flag: bool
    sent_count: int
    throttled: bool
