"""Tests de la evaluación (F4): las 4 ramas de `eval_type` y la escalada de pistas.

El LLM va mockeado: lo que se verifica no es la calidad del texto, sino las DECISIONES
que se toman a su alrededor — cuándo avanza el curso, cuándo se cuenta un intento, y la
regla que no se puede romper: nunca se entrega la solución, ni siquiera tras 4 intentos.
"""

from unittest.mock import MagicMock

import pytest

from course.models import CourseNode, UserState
from course.nodes import evaluate


def _nodo(eval_type, node_id="E1-08-02", **kw):
    return CourseNode(
        node_id=node_id,
        type="message",
        pauses=True,
        sends_content=False,
        description="Evalúa si el comando está bien escrito",
        eval_type=eval_type,
        **kw,
    )


@pytest.fixture
def llm(monkeypatch):
    """Mockea las dos fronteras de modelo y las escrituras al repositorio."""
    doble = MagicMock()
    doble.borrador = "texto del evaluador"
    doble.json = None

    # Se capturan las instrucciones que reciben los modelos: hay aserciones sobre lo
    # que se le pide al LLM, no solo sobre lo que devuelve.
    doble.instrucciones = []

    def _borrador(system, instruccion):
        doble.instrucciones.append(instruccion)
        return doble.borrador

    def _json(system, instruccion):
        doble.instrucciones.append(instruccion)
        return doble.json

    monkeypatch.setattr(evaluate, "generar_borrador", _borrador)
    monkeypatch.setattr(evaluate, "generar_json", _json)
    monkeypatch.setattr(evaluate, "aplicar_voz", lambda b: f"[spoky] {b}")
    monkeypatch.setattr(evaluate, "increment_attempts", doble.increment_attempts)
    monkeypatch.setattr(evaluate, "reset_attempts", doble.reset_attempts)
    monkeypatch.setattr(evaluate, "mark_for_review", doble.mark_for_review)
    monkeypatch.setattr(evaluate, "update_profile", doble.update_profile)
    return doble


ESTADO = UserState(phone="+34600111222", current_order=5, attempts=0)


def test_open_siempre_avanza(llm):
    mensaje, avanza = evaluate.evaluar(
        _nodo("open"), "creo que sirve para mostrar cosas", ESTADO, "+34600111222"
    )

    assert avanza is True
    assert mensaje.startswith("[spoky]")
    llm.increment_attempts.assert_not_called()


def test_strict_superado_avanza_y_reinicia_intentos(llm):
    llm.json = {"superado": True, "motivo": "sintaxis correcta"}

    mensaje, avanza = evaluate.evaluar(_nodo("strict"), "print('hola')", ESTADO, "+34600111222")

    assert avanza is True
    assert mensaje.startswith("[spoky]")
    llm.reset_attempts.assert_called_once_with("+34600111222")
    llm.increment_attempts.assert_not_called()


def test_strict_fallido_no_avanza_y_cuenta_intento(llm):
    llm.json = {"superado": False, "motivo": "faltan los paréntesis"}
    llm.increment_attempts.return_value = 1

    mensaje, avanza = evaluate.evaluar(_nodo("strict"), "print 'hola'", ESTADO, "+34600111222")

    assert avanza is False  # sigue en el mismo nodo
    assert mensaje.startswith("[spoky]")
    llm.increment_attempts.assert_called_once_with("+34600111222")
    llm.mark_for_review.assert_not_called()


@pytest.mark.parametrize("intento", [1, 2, 3])
def test_escalada_no_cierra_el_ejercicio_antes_del_cuarto(llm, intento):
    llm.json = {"superado": False}
    llm.increment_attempts.return_value = intento

    _, avanza = evaluate.evaluar(_nodo("strict"), "print 'hola'", ESTADO, "+34600111222")

    assert avanza is False
    llm.mark_for_review.assert_not_called()


def test_cuarto_intento_marca_para_repaso_y_avanza_sin_dar_la_solucion(llm):
    # §9 del plan: sustituye al «tras el 3.º dar la respuesta correcta» del documento v2.
    llm.json = {"superado": False}
    llm.increment_attempts.return_value = 4

    mensaje, avanza = evaluate.evaluar(_nodo("strict"), "no me sale", ESTADO, "+34600111222")

    assert avanza is True
    llm.mark_for_review.assert_called_once_with("+34600111222", "E1-08-02")
    llm.reset_attempts.assert_called_once_with("+34600111222")
    assert mensaje.startswith("[spoky]")


def test_escalada_usa_una_instruccion_distinta_por_intento():
    # Las 4 instrucciones existen y son distintas: sin esto, la escalada sería decorativa.
    from course.prompts import escalada

    textos = [escalada(i) for i in (1, 2, 3, 4)]
    assert len(set(textos)) == 4
    assert escalada(7) == escalada(4)  # 4+ comparten la última


def test_evaluacion_no_concluyente_no_penaliza_al_alumno(llm):
    # El modelo no devolvió JSON: es un fallo NUESTRO, no del alumno.
    llm.json = None

    _, avanza = evaluate.evaluar(_nodo("strict"), "print('hola')", ESTADO, "+34600111222")

    assert avanza is False
    llm.increment_attempts.assert_not_called()
    llm.mark_for_review.assert_not_called()


def test_ack_afirmativo_no_envia_nada(llm):
    # «Si - Nada» del CSV: confirmar no merece respuesta, solo seguir.
    llm.json = {"afirmativo": True}

    mensaje, avanza = evaluate.evaluar(
        _nodo("ack", node_id="R0-02"), "vale", ESTADO, "+34600111222"
    )

    assert mensaje is None
    assert avanza is True


def test_ack_negativo_agradece_y_avanza(llm):
    llm.json = {"afirmativo": False}

    mensaje, avanza = evaluate.evaluar(
        _nodo("ack", node_id="R0-02"), "ahora no puedo", ESTADO, "+34600111222"
    )

    assert mensaje.startswith("[spoky]")
    assert avanza is True


def test_register_completo_guarda_perfil_y_avanza(llm):
    llm.json = {
        "student_name": "Ana",
        "adult_name": "Laura Pérez",
        "adult_email": "laura@example.com",
        "adult_phone": "+34600222333",
        "faltan": [],
        "mensaje": "¡Bienvenida a bordo!",
    }

    mensaje, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"),
        "soy Ana, mi madre es Laura Pérez, laura@example.com, 600222333",
        ESTADO,
        "+34600111222",
    )

    assert avanza is True
    llm.update_profile.assert_called_once()
    guardado = llm.update_profile.call_args.kwargs
    assert guardado["student_name"] == "Ana"
    assert guardado["adult_email"] == "laura@example.com"
    assert "Bienvenida" in mensaje


def test_register_incompleto_pide_lo_que_falta_sin_avanzar(llm):
    llm.json = {
        "student_name": "Ana",
        "adult_name": None,
        "adult_email": None,
        "adult_phone": None,
        "faltan": ["adult_name", "adult_email", "adult_phone"],
        "mensaje": "Me falta el nombre de tu adulto",
    }

    mensaje, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"), "me llamo Ana", ESTADO, "+34600111222"
    )

    assert avanza is False  # el alta no se da por buena a medias
    # Lo que sí llegó se guarda: una segunda respuesta completa el resto.
    assert llm.update_profile.call_args.kwargs["student_name"] == "Ana"
    assert "falta" in mensaje


def test_register_sin_json_reintenta_sin_avanzar(llm):
    llm.json = None

    mensaje, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"), "🙂", ESTADO, "+34600111222"
    )

    assert avanza is False
    assert mensaje.startswith("[spoky]")
    llm.update_profile.assert_not_called()


PREGUNTA = "Indica que print es la forma de comunicarse; que ahora escriba su nombre"


def test_la_pregunta_del_catalogo_llega_al_evaluador(llm):
    # Sin esto el modelo juzga «si el comando está bien escrito» sin saber CUÁL se pidió.
    llm.json = {"superado": True}

    evaluate.evaluar(_nodo("strict", question=PREGUNTA), "print('Ana')", ESTADO, "+34600111222")

    assert PREGUNTA in llm.instrucciones[0]


def test_la_pregunta_llega_tambien_a_la_pista(llm):
    # Es donde más falta hace: una pista sin saber qué se pidió sería genérica.
    llm.json = {"superado": False}
    llm.increment_attempts.return_value = 2

    evaluate.evaluar(_nodo("strict", question=PREGUNTA), "print Ana", ESTADO, "+34600111222")

    assert any(PREGUNTA in i for i in llm.instrucciones)


def test_sin_pregunta_derivada_no_se_deja_hueco_vacio(llm):
    # Un nodo fuera del patrón de tres: la línea se omite entera, no queda ««»».
    llm.borrador = "feedback"

    evaluate.evaluar(_nodo("open"), "algo", ESTADO, "+34600111222")

    assert "«»" not in llm.instrucciones[0]
    assert "planteaste" not in llm.instrucciones[0]


def test_nodo_que_pausa_sin_eval_type_no_bloquea(llm):
    # Dato de catálogo incompleto: se acoge la respuesta y se sigue, nunca se atasca.
    _, avanza = evaluate.evaluar(_nodo(None), "algo", ESTADO, "+34600111222")

    assert avanza is True


# ── correcciones de la primera pasada real (claude/PLAN-fix-flujo-real.md) ──────────


def test_register_se_completa_en_dos_turnos(llm):
    """H6: el alumno reparte los datos en varios mensajes — que es lo que hace un niño de
    10-14 años, y lo que la propia instrucción del catálogo le permite. Lo que falta se
    mide sobre el perfil ACUMULADO; mirando solo la extracción del turno el alta no se
    completaría nunca y el curso quedaría atascado en el nodo 1."""
    # Primer turno: llegaron tres campos y ya están guardados en el estado.
    ya_guardado = UserState(
        phone="+34600111222",
        current_order=1,
        student_name="Ana",
        adult_name="Laura Pérez",
        adult_email="laura@example.com",
    )
    # Segundo turno: el alumno manda SOLO el teléfono que le faltaba.
    llm.json = {
        "student_name": None,
        "adult_name": None,
        "adult_email": None,
        "adult_phone": "+34600222333",
        "faltan": [],
        "mensaje": "¡Ya estamos! Bienvenida a bordo",
    }

    mensaje, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"), "600222333", ya_guardado, "+34600111222"
    )

    assert avanza is True
    assert "Bienvenida" in mensaje
    # No se pisa lo ya guardado con los None de esta extracción.
    assert llm.update_profile.call_args.kwargs == {
        "student_name": None,
        "adult_name": None,
        "adult_email": None,
        "adult_phone": "+34600222333",
    }


def test_register_incompleto_aunque_el_estado_traiga_parte(llm):
    """El contrapunto del anterior: acumular no puede dar por bueno un alta a la que
    todavía le falta un campo en ambos sitios."""
    ya_guardado = UserState(phone="+34600111222", current_order=1, student_name="Ana")
    llm.json = {
        "student_name": None,
        "adult_name": "Laura Pérez",
        "adult_email": None,
        "adult_phone": None,
        "faltan": ["adult_email", "adult_phone"],
        "mensaje": "Me falta el correo y el teléfono",
    }

    _, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"), "mi madre es Laura Pérez", ya_guardado, "+34600111222"
    )

    assert avanza is False


def test_register_completo_sin_mensaje_envia_bienvenida_igualmente(llm):
    """H1: en la primera pasada real el alta se completó y no se envió nada. El alumno
    estuvo cinco minutos sin señal de que el curso hubiera empezado."""
    llm.json = {
        "student_name": "Ana",
        "adult_name": "Laura Pérez",
        "adult_email": "laura@example.com",
        "adult_phone": "+34600222333",
        "faltan": [],
        "mensaje": "",  # el modelo no redactó nada
    }
    llm.borrador = "bienvenida a bordo, copiloto"

    mensaje, avanza = evaluate.evaluar(
        _nodo("register", node_id="R0-01"), "todos mis datos", ESTADO, "+34600111222"
    )

    assert avanza is True
    assert mensaje == "[spoky] bienvenida a bordo, copiloto"


def test_la_pregunta_literal_enviada_tiene_precedencia_sobre_la_del_catalogo(llm):
    """H4: `CourseNode.question` guarda la acotación de guion, a menudo en imperativo
    («Pregunta al humano si había escuchado sobre Python»), que el modelo lee como una
    orden y vuelve a formular. `UserState.last_question` es lo que el alumno leyó."""
    estado = UserState(
        phone="+34600111222",
        current_order=8,
        last_question="¿Qué sabes tú sobre Python, copiloto?",
    )
    nodo = _nodo("open", node_id="E1-01-02", question="Pregunta al humano, si habia esuchado…")

    evaluate.evaluar(nodo, "Es una serpiente", estado, "+34600111222")

    instruccion = llm.instrucciones[-1]
    assert "¿Qué sabes tú sobre Python, copiloto?" in instruccion
    assert "Pregunta al humano" not in instruccion


def test_sin_pregunta_literal_se_cae_al_catalogo(llm):
    """El respaldo: el primer turno tras un deploy, o una pausa sin texto previo."""
    estado = UserState(phone="+34600111222", current_order=8)
    nodo = _nodo("open", node_id="E1-01-02", question="Pregunta al humano si conoce Python")

    evaluate.evaluar(nodo, "Es una serpiente", estado, "+34600111222")

    assert "Pregunta al humano si conoce Python" in llm.instrucciones[-1]
