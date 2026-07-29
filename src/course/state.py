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

from .models import UserState


class CourseState(TypedDict, total=False):
    # identidad
    phone: str
    phone_number_id: str
    status: str  # "nuevo" | "registrado"
    # Estado persistido, cargado UNA vez en identify_user. Sin esto, cada nodo de texto
    # repetiría el GetItem para construir el system prompt (hasta 10 por invocación).
    # Se puede guardar el objeto tal cual porque este grafo no usa checkpointer.
    user: UserState | None
    # posición (espejo de CourseStateTable durante la invocación)
    current_order: int
    last_node_id: str | None
    waiting: bool
    # Texto literal del último mensaje de TEXTO enviado en esta invocación. Un nodo de
    # media lo pone a None: si lo último que vio el alumno fue un vídeo, no hay pregunta
    # que arrastrar y el evaluador debe caer al `question` del catálogo.
    last_question: str | None
    # entrada del alumno
    student_answer: str
    # control del loop
    course_completed: bool
    continue_flag: bool
    sent_count: int
    throttled: bool
    # Agujero en la numeración de la secuencia: no hay nodo en esta posición pero el
    # curso no ha terminado. No es fin de curso y tampoco se puede avanzar por encima.
    sequence_gap: bool
