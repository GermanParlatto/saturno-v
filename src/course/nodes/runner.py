"""Sequence Runner (§6 del documento): envía el nodo actual y decide pausar o seguir.

NO escribe en DynamoDB. El orden es deliberado — enviar primero y avanzar después, en el
nodo `advance` — porque el peor caso de esa secuencia es un mensaje duplicado, y el del
orden inverso es un nodo **saltado**. En un curso, duplicar > omitir (§2.4 del plan).

La ráfaga: entre `E1-01` y `E1-08` hay 7 nodos `pauses=false` seguidos. El loop inmediato
del documento los dispara en menos de un segundo — mala UX y arriesgado con los rate
limits de Meta. De ahí la pausa entre envíos.
"""

import os
import time

from shared.kapso_client import MEDIA_KINDS, send_media, send_text
from shared.observability import logger
from shared.whatsapp_format import format_for_whatsapp

from ..catalog import get_node_at
from ..state import CourseState


def _delay_seconds() -> float:
    return int(os.environ.get("INTER_MESSAGE_DELAY_MS", "1500")) / 1000


def sequence_runner(state: CourseState) -> CourseState:
    order = state["current_order"]
    nodo = get_node_at(order)

    if nodo is None:
        # Fin del curso: la posición ya no existe en la secuencia (§6.1 `if not node`).
        logger.info("Fin del curso", extra={"current_order": order})
        return {"course_completed": True, "continue_flag": False}

    enviados = state.get("sent_count", 0)

    if nodo.sends_content:
        if enviados:
            # Solo entre mensajes, nunca antes del primero: retrasar la respuesta
            # inicial se notaría como lentitud del bot.
            time.sleep(_delay_seconds())
        _enviar(state, nodo)
        enviados += 1

    if nodo.pauses:
        logger.info("Pausa esperando respuesta", extra={"node_id": nodo.node_id})
        return {
            "last_node_id": nodo.node_id,
            "waiting": True,
            "continue_flag": False,
            "sent_count": enviados,
        }

    return {
        "last_node_id": nodo.node_id,
        "waiting": False,
        "continue_flag": True,
        "sent_count": enviados,
    }


def _enviar(state: CourseState, nodo) -> None:
    """Envía el contenido del nodo: media si tiene fichero, texto si no."""
    phone_number_id = state["phone_number_id"]
    to = state["phone"]

    if nodo.file_url and nodo.media_kind in MEDIA_KINDS:
        send_media(phone_number_id, to=to, kind=nodo.media_kind, link=nodo.file_url)
        logger.info("Media enviada", extra={"node_id": nodo.node_id, "kind": nodo.media_kind})
        return

    # TODO F4: aquí `description` se envía tal cual. En F4 pasa por el LLM con el system
    # prompt de docs/07 para que salga en la voz de Spoky.
    texto = format_for_whatsapp(nodo.description)
    if not texto.strip():
        # Un nodo sin contenido enviable no es motivo para abortar la cadena: se salta.
        logger.warning("Nodo sin contenido que enviar", extra={"node_id": nodo.node_id})
        return
    send_text(phone_number_id, to=to, body=texto)
    logger.info("Texto enviado", extra={"node_id": nodo.node_id})
