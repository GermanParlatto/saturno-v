"""Nodo Finalizador: reescribe el borrador con la VOZ de Spoky. -> END

División del trabajo: el nodo `llm` (Bedrock) es el coordinador y tutor de
Python — responde de la CORRECCIÓN del contenido. Este nodo sólo pone la voz:
personaje, tono, calidez. Si falla, el borrador del tutor sale tal cual: el
usuario recibe una respuesta correcta aunque sin personaje. Nunca rompemos
el pipeline por esto.
"""

from aws_lambda_powertools.metrics import MetricUnit
from langchain_core.messages import AIMessage, RemoveMessage

from agents.prompts import REWRITE_INSTRUCTION, SPOKY_SYSTEM
from agents.state import AgentState
from shared import spoky_client
from shared.observability import logger, metrics
from shared.voice import MAX_TOKENS, TEMPERATURE, codigo_preservado


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

    if not codigo_preservado(borrador, final):
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
