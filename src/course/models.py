"""Modelos del motor de curso (Pydantic v2).

Dos entidades, deliberadamente separadas porque tienen naturalezas distintas:

- `CourseNode`  → definición ESTÁTICA de un nodo del curso (qué enviar, cómo evaluar).
                  Vive en `CourseCatalogTable`, se cachea en RAM.
- `UserState`   → estado MUTABLE de un alumno (dónde va, cuántos intentos lleva).
                  Vive en `CourseStateTable`, se escribe con frecuencia.

Los campos `eval_type`, `sends_content` y `media_kind` NO existen en los CSV de origen:
los deriva el seeder al sembrar (ver `tools/seed-course.py`). Aquí solo se declaran.
"""

from typing import Literal

from pydantic import BaseModel

# Enum de evaluación. Sustituye al parseo por substring de `logic` (español con tildes)
# que el documento v2 hacía en runtime: aquí es un dato limpio derivado offline.
#   open     → interpreta y comenta, siempre avanza (no hay respuesta correcta)
#   strict   → verifica un criterio (p. ej. sintaxis) y da feedback
#   ack      → acuse simple (Si/No), sin evaluación socrática
#   register → NO evalúa: extrae campos de perfil de la respuesta y los persiste.
#              Único caso hoy: R0-01, la posición 1 de la secuencia. Pausa como los
#              demás, pero lo que llega es un formulario en texto libre (nombre del
#              alumno + nombre/correo/teléfono del adulto), no un intento de ejercicio.
#              Sin esta rama, el primer mensaje de TODO alumno nuevo cae en un `else`
#              sin destino. Ver el TODO de F3 en claude/PLAN-course-engine.md.
EvalType = Literal["open", "strict", "ack", "register"]


class CourseNode(BaseModel):
    node_id: str
    type: str
    function: str | None = None
    pauses: bool
    description: str = ""
    # Derivados por el seeder:
    eval_type: EvalType | None = None
    # Qué debe hacer el LLM con la respuesta. En los nodos `-02` sale de su propia
    # `description`, que ya está redactada como instrucción.
    eval_instruction: str | None = None
    # La pregunta que este nodo evalúa: la `description` de su hermano `-01`. Sin ella
    # el evaluador juzgaría «si el comando está bien escrito» sin saber cuál se pidió.
    question: str | None = None
    output: str | None = None
    logic: str | None = None  # se conserva como nota editorial humana
    file_url: str | None = None
    media_kind: str | None = None  # image | video | document | text
    # false en nodos de evaluación pura (-02): generan el feedback DESPUÉS de la
    # respuesta, no envían nada antes de esperar.
    sends_content: bool = True


class UserState(BaseModel):
    phone: str
    # perfil (capturado en R0-01)
    student_name: str | None = None
    adult_name: str | None = None
    adult_email: str | None = None
    adult_phone: str | None = None
    created_at: str | None = None
    # contexto del system prompt (docs/07)
    juramento: str | None = None
    rango: str | None = None
    nivel_actual: str | None = None
    medalla_contador: int = 0
    # nodos cerrados sin superar tras agotar la escalada de pistas (4+ intentos).
    # No se entrega la solución: se anotan para repasarlos más adelante.
    review_nodes: list[str] = []
    # posición en el curso
    current_order: int = 0
    last_node_id: str | None = None
    waiting: bool = False
    attempts: int = 0
    # control de concurrencia / auditoría
    version: int = 0
    updated_at: str | None = None
    last_interaction_at: str | None = None
