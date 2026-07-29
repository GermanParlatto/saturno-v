"""Voz de Spoky: reescribe un borrador técnico con la personalidad del personaje.

Extraído de `agents/nodes/finalizer.py` para que el motor de curso lo reutilice sin
duplicar la salvaguarda del código. El finalizador legacy sigue usando
`codigo_preservado` desde aquí: una sola implementación de la guarda.

División del trabajo (la misma del grafo legacy): un modelo responde de la CORRECCIÓN
del contenido y este pone la VOZ. Si la voz falla, sale el borrador — el alumno recibe
algo correcto aunque sin personaje. Nunca se rompe el envío por esto.
"""

import re

from aws_lambda_powertools.metrics import MetricUnit

from agents.prompts import REWRITE_INSTRUCTION, SPOKY_SYSTEM
from shared import spoky_client
from shared.observability import logger, metrics

MAX_TOKENS = 200
TEMPERATURE = 0.6

# Bloques ```...``` e inline `...`. Sirve para la comprobación de integridad, no para
# renderizar (de eso ya se ocupa whatsapp_format.py con más matices).
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)


def codigo_preservado(borrador: str, final: str) -> bool:
    """True si todo fragmento de código del borrador sigue en la reescritura.

    El LoRA se entrenó para RESPONDER, no para reescribir: es una tarea fuera de
    distribución y un modelo de 2B puede alterar identificadores o sangría al
    reformular. Esta comprobación convierte ese fallo (código roto enviado a un niño)
    de silencioso a seguro.
    """
    fragmentos = _CODE_SPAN.findall(borrador)
    return all(frag in final for frag in fragmentos)


def aplicar_voz(borrador: str) -> str:
    """Devuelve el borrador en voz de Spoky, o el borrador tal cual si algo falla.

    No lanza: la voz es una mejora, no un requisito. Cualquier fallo (endpoint frío,
    401, estructura inválida, código alterado) degrada al borrador y queda registrado.
    """
    borrador = (borrador or "").strip()
    if not borrador:
        logger.warning("Sin borrador que reescribir: se omite la llamada a Spoky")
        metrics.add_metric(name="VozOmitida", unit=MetricUnit.Count, value=1)
        return ""

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
        # CUALQUIER fallo -> borrador. logger.exception deja el tipo concreto
        # (SpokyAuthError, SpokyTimeoutError...) sin tocar el token.
        logger.exception("La voz de Spoky falló: se envía el borrador")
        metrics.add_metric(name="VozFallback", unit=MetricUnit.Count, value=1)
        return borrador

    if not codigo_preservado(borrador, final):
        logger.warning("La voz alteró el código: se envía el borrador")
        metrics.add_metric(name="VozCodigoAlterado", unit=MetricUnit.Count, value=1)
        return borrador

    metrics.add_metric(name="VozOk", unit=MetricUnit.Count, value=1)
    return final
