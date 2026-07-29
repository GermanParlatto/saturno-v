"""Evaluación de la respuesta del alumno. Rutea por `eval_type` del nodo pausado.

    open     -> acoge la respuesta y avanza. No hay criterio que cumplir.
    strict   -> verifica el criterio. Si no lo cumple, NO avanza: escala pistas.
    ack      -> confirmación simple. Avanza en cualquier caso.
    register -> extrae el perfil de R0-01. Solo avanza con los cuatro campos.

Devuelve `(mensaje, avanza)`: el texto ya en voz de Spoky (o `None` si no hay nada que
decir) y si la posición debe moverse. Quien persiste es `progress.py`; aquí no se toca
la posición, solo `attempts` y el perfil, que son del nodo actual.

Regla que nunca se rompe (docs/07 y §9 del plan): **jamás se entrega la solución**.
Tras 4 intentos el ejercicio se cierra, se marca para repaso y la misión sigue.
"""

from shared.observability import logger
from shared.voice import aplicar_voz

from .. import prompts
from ..llm import generar_borrador, generar_json
from ..models import CourseNode, UserState
from ..repository import increment_attempts, mark_for_review, reset_attempts, update_profile

MAX_INTENTOS = 4

CAMPOS_PERFIL = ("student_name", "adult_name", "adult_email", "adult_phone")


def _instruccion(nodo: CourseNode) -> str:
    """Qué se le pide evaluar al modelo.

    `eval_instruction` es el campo dedicado, pero hoy solo lo tiene R0-01: en los nodos
    `-02` la `description` YA está redactada como instrucción («Evalúa si el comando
    está bien escrito»), así que sirve de fallback sin pérdida real de calidad.
    TODO: al cerrar F4, extraer las instrucciones a `EVAL_INSTRUCTIONS` del seeder.
    """
    return nodo.eval_instruction or nodo.description


def _pregunta(nodo: CourseNode, estado: UserState | None) -> str | None:
    """Qué se le planteó al alumno, con el texto REAL por delante del guion.

    `estado.last_question` es el mensaje literal que se le envió antes de pausar;
    `nodo.question` es la acotación editorial del catálogo, a menudo en imperativo
    («Pregunta al humano si había escuchado sobre Python»), que el modelo confunde con
    una orden y vuelve a formular en vez de responder (H4 de la primera pasada real).
    Se prefiere el literal y se cae al catálogo solo si no lo hay.
    """
    return (estado.last_question if estado else None) or nodo.question


def evaluar(
    nodo: CourseNode, respuesta: str, estado: UserState | None, phone: str
) -> tuple[str | None, bool]:
    system = prompts.system_prompt(estado, nodo)
    pregunta = _pregunta(nodo, estado)

    if nodo.eval_type == "register":
        return _registro(nodo, respuesta, system, phone, estado)
    if nodo.eval_type == "ack":
        return _acuse(respuesta, system)
    if nodo.eval_type == "strict":
        return _estricta(nodo, respuesta, system, estado, phone, pregunta)
    # `open` y cualquier nodo que pause sin tipo: acoger y seguir. Nunca bloquear al
    # alumno por un dato de catálogo incompleto.
    return _abierta(nodo, respuesta, system, pregunta)


def _abierta(
    nodo: CourseNode, respuesta: str, system: str, pregunta: str | None
) -> tuple[str, bool]:
    borrador = generar_borrador(
        system,
        prompts.con_pregunta(
            prompts.OPEN,
            pregunta,
            instruccion=_instruccion(nodo),
            respuesta=respuesta,
        ),
    )
    return aplicar_voz(borrador), True


def _acuse(respuesta: str, system: str) -> tuple[str | None, bool]:
    datos = generar_json(system, prompts.ACK.format(respuesta=respuesta))
    # Sin JSON utilizable se asume confirmación: es la rama que no molesta al alumno.
    if datos is None or datos.get("afirmativo"):
        return None, True  # «Si - Nada»: se avanza sin decir nada
    borrador = generar_borrador(system, prompts.ACK_AGRADECIMIENTO.format(respuesta=respuesta))
    return aplicar_voz(borrador), True


def _estricta(
    nodo: CourseNode,
    respuesta: str,
    system: str,
    estado: UserState | None,
    phone: str,
    pregunta: str | None,
) -> tuple[str, bool]:
    veredicto = generar_json(
        system,
        prompts.con_pregunta(
            prompts.STRICT,
            pregunta,
            instruccion=_instruccion(nodo),
            respuesta=respuesta,
        ),
    )

    if veredicto is None:
        # El evaluador no fue concluyente. NO se cuenta como fallo del alumno: se le
        # pide que lo intente otra vez sin penalizar el contador de intentos.
        logger.warning("Evaluación no concluyente", extra={"node_id": nodo.node_id})
        borrador = generar_borrador(
            system,
            "Las lecturas del ordenador de a bordo llegan con interferencias. Pídele al "
            "copiloto que te lo repita, con calidez y sin culparle de nada.",
        )
        return aplicar_voz(borrador), False

    if veredicto.get("superado"):
        reset_attempts(phone)
        borrador = generar_borrador(
            system,
            f"El copiloto ha resuelto el ejercicio. Su respuesta: «{respuesta}». "
            "Celébralo nombrando QUÉ hizo bien (el proceso, no su inteligencia) y "
            "seguid la misión.",
        )
        return aplicar_voz(borrador), True

    intentos = increment_attempts(phone)
    logger.info("Intento fallido", extra={"node_id": nodo.node_id, "intentos": intentos})

    # La pregunta importa sobre todo AQUÍ: una pista sin saber qué se pidió sería
    # genérica, y la escalada de los 4 niveles depende de poder señalar el punto exacto.
    borrador = generar_borrador(
        system,
        prompts.con_pregunta(
            prompts.PISTA,
            pregunta,
            instruccion=_instruccion(nodo),
            respuesta=respuesta,
            escalada=prompts.escalada(intentos),
        ),
    )
    mensaje = aplicar_voz(borrador)

    if intentos >= MAX_INTENTOS:
        # Se cierra el ejercicio y se avanza SIN entregar la solución (§9 del plan).
        mark_for_review(phone, nodo.node_id)
        reset_attempts(phone)
        return mensaje, True

    return mensaje, False


def _registro(
    nodo: CourseNode, respuesta: str, system: str, phone: str, estado: UserState | None
) -> tuple[str | None, bool]:
    datos = generar_json(
        system, prompts.REGISTER.format(instruccion=_instruccion(nodo), respuesta=respuesta)
    )

    if datos is None:
        borrador = generar_borrador(
            system,
            "No has podido leer los datos del copiloto. Pídele otra vez, con calidez y "
            "en una sola burbuja, su nombre y el nombre, correo y teléfono de su adulto "
            "responsable.",
        )
        return aplicar_voz(borrador), False

    # Nunca se loguean los valores: son datos de contacto de un adulto responsable de
    # un menor. Solo qué campos faltan.
    perfil = {c: datos.get(c) for c in CAMPOS_PERFIL}
    update_profile(phone, **perfil)

    # Qué falta se mide sobre el perfil ACUMULADO, no sobre la extracción de este turno.
    # Un alumno de 10-14 años reparte los datos en varios mensajes (y la propia
    # instrucción del catálogo lo prevé): mirar solo lo de ahora dejaría el alta sin
    # completarse nunca, con el curso atascado en el nodo 1.
    faltan = [
        c
        for c in CAMPOS_PERFIL
        if not (perfil.get(c) or (getattr(estado, c, None) if estado else None))
    ]
    mensaje = (datos.get("mensaje") or "").strip()

    if faltan:
        logger.info("Alta incompleta", extra={"faltan": faltan})
        return aplicar_voz(mensaje) if mensaje else None, False

    logger.info("Alta completada")
    if not mensaje:
        # Nunca cerrar el alta en silencio: el alumno acaba de entregar sus datos y sin
        # acuse no sabe si el curso ha empezado. En la primera pasada real esto dejó a
        # un alumno cinco minutos sin respuesta (H1).
        mensaje = generar_borrador(
            system,
            "El copiloto acaba de completar su registro en la Bitácora. Dale la "
            "bienvenida a bordo en una sola burbuja breve y anúnciale que la misión "
            "empieza ya. No le pidas ningún dato más.",
        )
    return aplicar_voz(mensaje), True
