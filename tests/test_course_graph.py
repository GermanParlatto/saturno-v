"""Tests del grafo del curso (F3): recorrido, pausa, reanudación y guardas.

Se mockean las tres fronteras externas —catálogo, repositorio y envío por Kapso— para
poder ejercitar el grafo entero sin AWS ni red. Lo que se verifica es el COMPORTAMIENTO
observable: qué se envía, en qué orden, y cómo queda la posición del alumno.
"""

from unittest.mock import MagicMock

import pytest

from course.models import CourseNode, UserState
from course.repository import PositionConflict


def _nodo(node_id, **kw):
    base = {
        "node_id": node_id,
        "type": "message",
        "pauses": False,
        "sends_content": True,
        "description": f"contenido de {node_id}",
    }
    base.update(kw)
    return CourseNode(**base)


def _estado(phone="+34600111222", **kw):
    base = {"phone": phone, "current_order": 1, "version": 1, "waiting": False}
    base.update(kw)
    return UserState(**base)


@pytest.fixture
def curso(monkeypatch):
    """Cablea el grafo contra dobles y expone lo que se envió y lo que se persistió."""
    monkeypatch.setenv("INTER_MESSAGE_DELAY_MS", "0")  # sin esperas reales en test
    monkeypatch.setenv("MAX_NODES_PER_INVOCATION", "10")
    monkeypatch.setenv("QUEUE_URL", "https://sqs.test/queue")

    import course.nodes.advance as advance_mod
    import course.nodes.identify as identify_mod
    import course.nodes.progress as progress_mod
    import course.nodes.runner as runner_mod

    doble = MagicMock()
    doble.secuencia = {}  # order -> CourseNode
    doble.nodos = {}  # node_id -> CourseNode
    doble.estado = None  # UserState | None

    monkeypatch.setattr(runner_mod, "get_node_at", lambda o: doble.secuencia.get(o))
    monkeypatch.setattr(progress_mod, "get_node", lambda nid: doble.nodos.get(nid))
    monkeypatch.setattr(identify_mod, "get_user_state", lambda p: doble.estado)
    monkeypatch.setattr(progress_mod, "get_user_state", lambda p: doble.estado)

    monkeypatch.setattr(runner_mod, "send_text", doble.send_text)
    monkeypatch.setattr(runner_mod, "send_media", doble.send_media)
    monkeypatch.setattr(advance_mod, "set_waiting", doble.set_waiting)
    monkeypatch.setattr(advance_mod, "advance_position", doble.advance_position)
    monkeypatch.setattr(progress_mod, "advance_position", doble.advance_progress)
    monkeypatch.setattr(advance_mod, "enqueue_continuation", doble.enqueue_continuation)

    def _create_user(phone, **kw):
        doble.estado = _estado(phone)
        return doble.estado

    import course.nodes.register as register_mod

    monkeypatch.setattr(register_mod, "create_user", _create_user)

    from course.app import run_course

    doble.run = lambda text="hola": run_course("+34600111222", text, "PNID")
    return doble


def test_alumno_nuevo_arranca_en_el_nodo_1(curso):
    curso.secuencia = {1: _nodo("R0-01", pauses=True)}
    curso.nodos = {"R0-01": curso.secuencia[1]}

    final = curso.run()

    curso.send_text.assert_called_once()
    assert "R0-01" in curso.send_text.call_args.kwargs["body"]
    assert final["waiting"] is True
    curso.set_waiting.assert_called_once_with("+34600111222", True)
    # Un nodo que pausa NO avanza la posición: sigue pendiente de respuesta.
    curso.advance_position.assert_not_called()


def test_encadena_nodos_que_no_pausan_hasta_el_que_pausa(curso):
    curso.secuencia = {
        1: _nodo("E1-01"),
        2: _nodo("E1-02"),
        3: _nodo("E1-03", pauses=True),
    }
    curso.estado = _estado(current_order=1)

    final = curso.run()

    assert curso.send_text.call_count == 3
    assert final["waiting"] is True
    # Solo avanzan los dos que no pausan.
    assert curso.advance_position.call_count == 2


def test_media_usa_send_media_y_no_send_text(curso):
    curso.secuencia = {
        1: _nodo("E1-01", type="comic", media_kind="image", file_url="https://x/E1-01.png"),
        2: _nodo("E1-02", pauses=True),
    }
    curso.estado = _estado(current_order=1)

    curso.run()

    curso.send_media.assert_called_once()
    assert curso.send_media.call_args.kwargs["kind"] == "image"
    assert curso.send_media.call_args.kwargs["link"] == "https://x/E1-01.png"


def test_responder_reanuda_desde_la_pausa(curso):
    # El alumno estaba esperando en el nodo 1 y responde: avanza al 2.
    curso.secuencia = {1: _nodo("R0-01", pauses=True), 2: _nodo("R0-02", pauses=True)}
    curso.nodos = {"R0-01": curso.secuencia[1]}
    curso.estado = _estado(current_order=1, waiting=True, last_node_id="R0-01")

    final = curso.run("me llamo Ana")

    curso.advance_progress.assert_called_once()
    assert curso.advance_progress.call_args.kwargs["expected_order"] == 1
    assert final["current_order"] == 2
    assert "R0-02" in curso.send_text.call_args.kwargs["body"]


def test_nodo_sin_contenido_no_envia_pero_no_corta_la_cadena(curso):
    # Los nodos -02 (sends_content=False) solo evalúan: no mandan nada antes de esperar.
    curso.secuencia = {
        1: _nodo("E1-08-02", pauses=True, sends_content=False, eval_type="open"),
    }
    curso.estado = _estado(current_order=1)

    final = curso.run()

    curso.send_text.assert_not_called()
    curso.send_media.assert_not_called()
    assert final["waiting"] is True


def test_fin_de_curso_cuando_la_posicion_no_existe(curso):
    curso.secuencia = {}  # nada en la posición 1
    curso.estado = _estado(current_order=1)

    final = curso.run()

    assert final["course_completed"] is True
    curso.send_text.assert_not_called()
    curso.advance_position.assert_not_called()


def test_tope_por_invocacion_reencola_en_vez_de_seguir(curso, monkeypatch):
    monkeypatch.setenv("MAX_NODES_PER_INVOCATION", "3")
    # Cadena larga de nodos que no pausan: sin guarda, se enviarían los 6 de golpe.
    curso.secuencia = {i: _nodo(f"E1-{i:02d}") for i in range(1, 7)}
    curso.estado = _estado(current_order=1)

    final = curso.run()

    assert curso.send_text.call_count == 3
    curso.enqueue_continuation.assert_called_once_with("+34600111222", "PNID")
    assert final["throttled"] is True


def test_conflicto_de_posicion_corta_la_cadena(curso):
    # Reentrega tardía de SQS: otra invocación ya avanzó desde esta posición.
    curso.secuencia = {1: _nodo("E1-01"), 2: _nodo("E1-02")}
    curso.estado = _estado(current_order=1)
    curso.advance_position.side_effect = PositionConflict("ya avanzó")

    final = curso.run()

    # Se envió el nodo actual (duplicado aceptable) pero NO se encadena el siguiente:
    # duplicar un mensaje es tolerable, saltarse un nodo no.
    assert curso.send_text.call_count == 1
    assert final.get("continue_flag") is False
