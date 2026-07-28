"""Nodo Finalizador: reescribe el borrador con la VOZ de Spoky. -> END

División del trabajo: el nodo `llm` (Bedrock) es el coordinador y tutor de
Python — responde de la CORRECCIÓN del contenido. Este nodo sólo pone la voz:
personaje, tono, calidez. Si falla, el borrador del tutor sale tal cual: el
usuario recibe una respuesta correcta aunque sin personaje. Nunca rompemos
el pipeline por esto.
"""

import re

from aws_lambda_powertools.metrics import MetricUnit
from langchain_core.messages import AIMessage, RemoveMessage

from agents.prompts import REWRITE_INSTRUCTION, SPOKY_SYSTEM
from agents.state import AgentState
from shared import spoky_client
from shared.observability import logger, metrics

MAX_TOKENS = 200
TEMPERATURE = 0.6

# Fragmentos de código a preservar: bloques ```...``` e inline `...`. Se usa
# para la comprobación de integridad, no para renderizado (whatsapp_format.py
# ya cubre eso con más matices); aquí sólo importa detectar qué texto entre
# comillas invertidas existía en el borrador y verificar que sigue presente.
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)


def _codigo_preservado(borrador: str, final: str) -> bool:
    """True si todo fragmento de código del borrador sigue en la reescritura.

    El LoRA se entrenó para RESPONDER, no para reescribir: es una tarea fuera
    de distribución y un modelo de 2B puede alterar identificadores o
    sangría al reformular. Esta comprobación convierte ese fallo (código roto
    enviado a un niño) de silencioso a seguro: si falta algún fragmento, se
    descarta la reescritura y se usa el borrador.
    """
    fragmentos = _CODE_SPAN.findall(borrador)
    return all(frag in final for frag in fragmentos)


def finalizer(state: AgentState) -> dict:
    """Sustituye el borrador del tutor por su versión en voz de Spoky."""
    mensajes = state.get("messages") or []
    draft = mensajes[-1] if mensajes else None

    # Guarda 1: sin borrador utilizable no hay nada que reescribir, y sobre
    # todo NO gastamos una llamada al endpoint. Devolvemos {}: el reducer no
    # escribe nada y el historial queda como estaba.
    if draft is None or not isinstance(draft, AIMessage) or not draft.text.strip():
        logger.warning("Finalizador sin borrador válido: se omite la llamada")
        metrics.add_metric(name="FinalizerOmitido", unit=MetricUnit.Count, value=1)
        return {}

    borrador = draft.text.strip()

    try:
        final = spoky_client.generar(
            [
                {"role": "system", "content": SPOKY_SYSTEM},
                {"role": "user", "content": REWRITE_INSTRUCTION.format(borrador=borrador)},
            ],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
    except Exception:
        # CUALQUIER fallo -> el borrador se envía. logger.exception incluye el
        # tipo concreto (SpokyAuthError, SpokyTimeoutError...) y el traceback,
        # sin tocar el token ni el cuerpo de la respuesta.
        logger.exception("Finalizador falló: se envía el borrador del tutor")
        metrics.add_metric(name="FinalizerFallback", unit=MetricUnit.Count, value=1)
        return {}

    if not _codigo_preservado(borrador, final):
        logger.warning("Finalizador alteró el código: se envía el borrador")
        metrics.add_metric(name="FinalizerCodigoAlterado", unit=MetricUnit.Count, value=1)
        return {}

    metrics.add_metric(name="FinalizerOk", unit=MetricUnit.Count, value=1)

    # Guarda 2: sin id no podemos borrar. add_messages lanza ValueError si el
    # id del RemoveMessage no existe en el historial, y eso tumbaría el grafo.
    if not draft.id:
        logger.warning("Borrador sin id: se añade la versión Spoky sin sustituir")
        return {"messages": [AIMessage(content=final)]}

    # Sustitución atómica: un solo write al reducer. El historial persistido
    # refleja exactamente lo que el usuario leyó, no el borrador intermedio.
    return {"messages": [RemoveMessage(id=draft.id), AIMessage(content=final)]}
