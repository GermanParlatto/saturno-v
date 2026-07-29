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
from shared.voice import aplicar_voz
from shared.whatsapp_format import format_for_whatsapp

from ..catalog import get_node_at, max_order
from ..llm import generar_borrador
from ..prompts import system_prompt
from ..state import CourseState


def _delay_seconds() -> float:
    return int(os.environ.get("INTER_MESSAGE_DELAY_MS", "1500")) / 1000


def sequence_runner(state: CourseState) -> CourseState:
    order = state["current_order"]
    nodo = get_node_at(order)

    if nodo is None:
        if order <= max_order():
            # HUECO en la secuencia, no fin de curso: la posición existe dentro del rango
            # del catálogo pero no tiene nodo. Pasaría si se retira un nodo sin renumerar.
            # Tratarlo como fin de curso graduaría en silencio a todos los alumnos, así
            # que se corta la invocación con un error visible en CloudWatch.
            logger.error(
                "Hueco en la secuencia del curso",
                extra={"current_order": order, "max_order": max_order()},
            )
            return {"sequence_gap": True, "continue_flag": False}
        # Fin del curso: la posición ya no existe en la secuencia (§6.1 `if not node`).
        logger.info("Fin del curso", extra={"current_order": order})
        return {"course_completed": True, "continue_flag": False}

    enviados = state.get("sent_count", 0)
    ultima_pregunta = state.get("last_question")

    if nodo.sends_content:
        if enviados:
            # Solo entre mensajes, nunca antes del primero: retrasar la respuesta
            # inicial se notaría como lentitud del bot.
            time.sleep(_delay_seconds())
        # Lo que se acaba de enviar pasa a ser el contexto del próximo evaluador: si fue
        # texto, es la pregunta que el alumno leyó; si fue media, no hay pregunta que
        # arrastrar y la anterior se descarta por obsoleta.
        ultima_pregunta = _enviar(state, nodo)
        enviados += 1

    if nodo.pauses:
        logger.info("Pausa esperando respuesta", extra={"node_id": nodo.node_id})
        return {
            "last_node_id": nodo.node_id,
            "waiting": True,
            "continue_flag": False,
            "sent_count": enviados,
            "last_question": ultima_pregunta,
        }

    return {
        "last_node_id": nodo.node_id,
        "waiting": False,
        "continue_flag": True,
        "sent_count": enviados,
        "last_question": ultima_pregunta,
    }


def _enviar(state: CourseState, nodo) -> str | None:
    """Envía el contenido del nodo: media si tiene fichero, texto si no.

    Devuelve el texto enviado, o `None` si fue media o no se envió nada. El llamador lo
    usa como `last_question` del turno siguiente.
    """
    phone_number_id = state["phone_number_id"]
    to = state["phone"]

    if nodo.file_url and nodo.media_kind in MEDIA_KINDS:
        send_media(phone_number_id, to=to, kind=nodo.media_kind, link=nodo.file_url)
        logger.info("Media enviada", extra={"node_id": nodo.node_id, "kind": nodo.media_kind})
        return None

    if not (nodo.description or "").strip():
        # Un nodo sin contenido enviable no es motivo para abortar la cadena: se salta.
        logger.warning("Nodo sin contenido que enviar", extra={"node_id": nodo.node_id})
        return None

    # `description` es una INSTRUCCIÓN de guion («Indica que print es la forma de
    # comunicarse»), no el texto a enviar: mandarla tal cual sería enviarle al alumno
    # la nota del guionista. Se genera el contenido y se le pone la voz de Spoky.
    #
    # Las dos prohibiciones del final son correcciones de fallos vistos en la primera
    # pasada real (H5 en claude/PLAN-fix-flujo-real.md): el modelo inventó una respuesta
    # previa inexistente y pidió «una lista en Python» en el Episodio 1, concepto que el
    # curso no introduce hasta el Episodio 4.
    borrador = generar_borrador(
        system_prompt(state.get("user"), nodo),
        f"Dirígete a tu copiloto para esta parte de la misión: «{nodo.description}»\n\n"
        "Es contenido nuevo, no una corrección: no evalúes nada, no menciones ni supongas "
        "respuestas anteriores del copiloto, y no te refieras a nada que él haya dicho.\n"
        "No introduzcas conceptos, ejercicios ni vocabulario de Python que no aparezcan "
        "explícitamente en esa instrucción: el copiloto aún no los ha aprendido.",
    )
    texto = format_for_whatsapp(aplicar_voz(borrador))
    if not texto.strip():
        logger.warning("Generación vacía para el nodo", extra={"node_id": nodo.node_id})
        return None
    send_text(phone_number_id, to=to, body=texto)
    logger.info("Texto enviado", extra={"node_id": nodo.node_id})
    return texto
