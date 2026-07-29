"""Tests de las derivaciones del seeder del catálogo.

Son funciones puras sobre los CSV: se prueban sin AWS ni `moto`. Lo que cubren es el
contrato del que depende la evaluación — que el catálogo llegue a DynamoDB con la
instrucción Y la pregunta, porque sin la segunda el evaluador juzga a ciegas.

El fichero se carga por ruta porque `tools/seed-course.py` lleva guion en el nombre y no
es importable como módulo.
"""

import importlib.util
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parent.parent / "tools" / "seed-course.py"
_spec = importlib.util.spec_from_file_location("seed_course", _RUTA)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


# ── eval_type ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "logic,pausa,esperado",
    [
        ("No existe un criterio de éxito para la respuesta", True, "open"),
        # Misma frase SIN tildes: la clasificación no puede depender de ellas.
        ("No existe un criterio de exito para la respuesta", True, "open"),
        ("Se evalua que la sintaxis este correcta", True, "strict"),
        ("Si - Nada\nNo - Mensaje de agradecimiento", True, "ack"),
        ("", True, "register"),  # pausa sin criterio = captura de datos (R0-01)
        ("cualquier cosa", False, None),  # no pausa = no evalúa
    ],
)
def test_derive_eval_type(logic, pausa, esperado):
    assert seed.derive_eval_type(logic, pausa) == esperado


# ── eval_instruction ────────────────────────────────────────────────────────────────
#
# El criterio ya no es el sufijo `-02` del node_id sino `es_evaluacion` (el nodo pausa y
# no tiene nada que enviar). `E0-02-01` es un nodo de evaluación con nomenclatura de
# pregunta: con el criterio anterior se quedaba sin instrucción y sin pregunta.


def test_eval_instruction_promociona_la_description_de_un_nodo_de_evaluacion():
    # En los nodos que evalúan, la description YA está escrita como instrucción al LLM.
    assert (
        seed.derive_eval_instruction(
            "E1-08-02", "Evalua si el comando esta bien escrito", es_evaluacion=True
        )
        == "Evalua si el comando esta bien escrito"
    )


def test_eval_instruction_respeta_el_override_del_diccionario():
    # R0-01 no es un nodo de evaluación (pausa pero envía su imagen): su instrucción se
    # escribe a mano y tiene precedencia aunque `es_evaluacion` sea False.
    derivada = seed.derive_eval_instruction(
        "R0-01", "Información del Proyecto Waku Code", es_evaluacion=False
    )
    assert derivada == seed.EVAL_INSTRUCTIONS["R0-01"]
    assert "Extrae" in derivada


def test_eval_instruction_es_none_en_un_nodo_de_contenido():
    assert seed.derive_eval_instruction("E1-08", "¡La nave despierta!", es_evaluacion=False) is None


def test_eval_instruction_es_none_si_la_description_esta_vacia():
    assert seed.derive_eval_instruction("E1-08-02", "   ", es_evaluacion=True) is None


# ── question ────────────────────────────────────────────────────────────────────────


def test_question_sale_del_nodo_anterior_en_la_secuencia():
    anterior = {"E1-08-02": "Indica que print es la forma de comunicarse; que escriba su nombre"}

    assert seed.derive_question("E1-08-02", anterior, es_evaluacion=True) == anterior["E1-08-02"]


def test_question_es_none_sin_nodo_anterior():
    # Primer nodo de la secuencia: no hay nada delante de lo que derivarla.
    assert seed.derive_question("R0-01", {}, es_evaluacion=True) is None


def test_question_es_none_en_nodos_que_no_evaluan():
    anterior = {"E1-02": "cómic anterior"}

    # E1-02 termina en "-02" pero es contenido, no evaluación: no pausa.
    assert seed.derive_question("E1-02", anterior, es_evaluacion=False) is None
    assert seed.derive_eval_instruction("E1-02", "otro cómic", es_evaluacion=False) is None


# ── sends_content ───────────────────────────────────────────────────────────────────


def test_sends_content_falso_en_todo_nodo_que_pausa_sin_fichero():
    # Un nodo que pausa sin fichero solo espera y evalúa: su description es la
    # instrucción del evaluador y mandarla sería enviarle al alumno la nota de guion.
    assert seed.derive_sends_content(pauses=True, file_url="") is False
    assert seed.derive_sends_content(pauses=True, file_url="   ") is False
    # R0-01 sí envía (la imagen del aviso legal) Y ADEMÁS espera.
    assert seed.derive_sends_content(pauses=True, file_url="https://…/R0-01.png") is True
    # Los nodos de contenido siempre envían, con fichero o generando texto.
    assert seed.derive_sends_content(pauses=False, file_url="") is True


# ── secuencia ───────────────────────────────────────────────────────────────────────


def test_la_secuencia_se_numera_por_posicion_de_fila():
    """La columna `order` del CSV se ignora: numerar por posición hace imposible un
    hueco, y un hueco haría que `get_node_at` devolviera None y el curso terminara en
    silencio a mitad (ver H8 de claude/PLAN-fix-flujo-real.md)."""
    flow = [
        {"id": "1", "order": "1", "node_id": "R0-01"},
        # `order` saltado a propósito, como quedaría al borrar una fila sin renumerar.
        {"id": "3", "order": "3", "node_id": "E0-01"},
        {"id": "4", "order": "99", "node_id": "E0-02"},
    ]

    assert seed.build_sequence(flow) == ["R0-01", "E0-01", "E0-02"]


def test_r0_02_ya_no_esta_en_la_secuencia_real():
    """Decisión de producto: R0-02 era una pausa muda (imagen celebratoria que no
    preguntaba nada) y dejaba el curso esperando una respuesta que nunca se pidió."""
    _, flow = seed.load_rows()
    secuencia = seed.build_sequence(flow)

    assert "R0-02" not in secuencia
    assert secuencia[:4] == ["R0-01", "E0-01", "E0-02", "E0-02-01"]


def test_la_secuencia_real_no_tiene_node_ids_repetidos():
    _, flow = seed.load_rows()
    secuencia = seed.build_sequence(flow)

    assert len(secuencia) == len(set(secuencia))


# ── integración sobre los CSV reales ────────────────────────────────────────────────


def _derivar_todo():
    nodes, flow = seed.load_rows()
    secuencia = seed.build_sequence(flow)
    descripciones = {
        (r.get("id") or "").strip(): (r.get("description") or "").strip() for r in nodes
    }
    anterior = {
        nid: descripciones.get(secuencia[i - 1], "") for i, nid in enumerate(secuencia) if i > 0
    }
    items = {}
    for row in nodes:
        node_id = (row.get("id") or "").strip()
        if not node_id:
            continue
        items[node_id], _ = seed._row_to_item(row, anterior)
    return items


def test_los_csv_reales_no_dejan_ningun_nodo_de_evaluacion_incompleto():
    """El invariante que sostiene toda la evaluación: todo nodo que pausa sin nada que
    enviar tiene instrucción Y pregunta. Si alguien edita los CSV y rompe el patrón de
    tres nodos, salta aquí."""
    incompletos = [
        nid
        for nid, item in _derivar_todo().items()
        if item["pauses"]
        and not item["sends_content"]
        and (not item.get("eval_instruction") or not item.get("question"))
    ]

    assert incompletos == []


def test_ningun_nodo_real_pausa_enviando_texto_generado():
    """El fallo de E0-02-01 en la primera pasada real: pausaba con `sends_content=true`
    y sin fichero, así que el runner generó un mensaje a partir de «Evalúa la respuesta
    del usuario» y se lo mandó al alumno."""
    culpables = [
        nid
        for nid, item in _derivar_todo().items()
        if item["pauses"] and item["sends_content"] and item.get("media_kind") == "text"
    ]

    assert culpables == []


def test_e0_02_01_queda_completo():
    """El nodo que se escapaba de las tres derivaciones por llamarse `-01`."""
    item = _derivar_todo()["E0-02-01"]

    assert item["pauses"] is True
    assert item["sends_content"] is False
    assert item["eval_instruction"] == "Evalua la respuesta del usuario, (emoji, audio, sticker)."
    # Su pregunta es la del vídeo que le precede: «…cierra con ¿Aceptas la misión?»
    assert "Aceptas la misión" in item["question"]


# ── purga de posiciones sobrantes ───────────────────────────────────────────────────


class _TablaFalsa:
    """Doble mínimo de una tabla DynamoDB: solo lo que usa `purge_stale_flow`."""

    def __init__(self, items=None):
        self.items = dict(items or {})

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        pk = cond._values[0]._values[1]
        limite = cond._values[1]._values[1]
        return {"Items": [i for (p, s), i in self.items.items() if p == pk and s > limite]}

    def batch_writer(self):
        tabla = self

        class _W:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def delete_item(self, Key):
                tabla.items.pop((Key["PK"], Key["SK"]), None)

        return _W()


def test_la_purga_borra_las_posiciones_que_sobran_al_acortar(monkeypatch):
    """H8: `batch_writer` solo hace `put_item`, nunca borra. Al pasar de 70 a 69
    posiciones, `ORD#000070` sobreviviría apuntando al nodo que estaba ahí antes y el
    curso repetiría el último nodo en vez de terminar."""
    tabla = _TablaFalsa(
        {
            ("FLOW#waku-l0", f"ORD#{i:06d}"): {"PK": "FLOW#waku-l0", "SK": f"ORD#{i:06d}"}
            for i in range(1, 71)
        }
    )
    # Un nodo de otra PK que NO debe tocarse.
    tabla.items[("NODE#EF-07", "META")] = {"PK": "NODE#EF-07", "SK": "META"}
    monkeypatch.setattr(seed, "_table", lambda _: tabla)

    borrados = seed.purge_stale_flow("cualquiera", "waku-l0", length=69)

    assert borrados == 1
    assert ("FLOW#waku-l0", "ORD#000070") not in tabla.items
    assert ("FLOW#waku-l0", "ORD#000069") in tabla.items
    assert ("NODE#EF-07", "META") in tabla.items


def test_la_purga_no_borra_nada_si_la_secuencia_no_se_acorto(monkeypatch):
    tabla = _TablaFalsa(
        {
            ("FLOW#waku-l0", f"ORD#{i:06d}"): {"PK": "FLOW#waku-l0", "SK": f"ORD#{i:06d}"}
            for i in range(1, 70)
        }
    )
    monkeypatch.setattr(seed, "_table", lambda _: tabla)

    assert seed.purge_stale_flow("cualquiera", "waku-l0", length=69) == 0
    assert len(tabla.items) == 69
