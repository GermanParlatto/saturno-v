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
#   open   → interpreta y comenta, siempre avanza (no hay respuesta correcta)
#   strict → verifica un criterio (p. ej. sintaxis) y da feedback
#   ack    → acuse simple (Si/No), sin evaluación socrática
EvalType = Literal["open", "strict", "ack"]


class CourseNode(BaseModel):
    node_id: str
    type: str
    function: str | None = None
    pauses: bool
    description: str = ""
    # Derivados por el seeder:
    eval_type: EvalType | None = None
    eval_instruction: str | None = None  # se separa de `description` en pasada posterior
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
    # posición en el curso
    current_order: int = 0
    last_node_id: str | None = None
    waiting: bool = False
    attempts: int = 0
    # control de concurrencia / auditoría
    version: int = 0
    updated_at: str | None = None
    last_interaction_at: str | None = None
