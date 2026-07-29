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


def test_eval_instruction_promociona_la_description_de_un_nodo_02():
    # En los -02 la description YA está escrita como instrucción para el LLM.
    assert (
        seed.derive_eval_instruction("E1-08-02", "Evalua si el comando esta bien escrito")
        == "Evalua si el comando esta bien escrito"
    )


def test_eval_instruction_respeta_el_override_del_diccionario():
    # R0-01 no sigue el patrón -02: su instrucción se escribe a mano y tiene precedencia.
    derivada = seed.derive_eval_instruction("R0-01", "Información del Proyecto Waku Code")

    assert derivada == seed.EVAL_INSTRUCTIONS["R0-01"]
    assert "Extrae" in derivada


def test_eval_instruction_es_none_en_un_nodo_de_contenido():
    assert seed.derive_eval_instruction("E1-08", "¡La nave despierta!") is None


def test_eval_instruction_es_none_si_la_description_esta_vacia():
    assert seed.derive_eval_instruction("E1-08-02", "   ") is None


# ── question ────────────────────────────────────────────────────────────────────────


def test_question_sale_de_la_description_del_hermano_01():
    descripciones = {
        "E1-08": "La nave despierta",
        "E1-08-01": "Indica que print es la forma de comunicarse; que escriba su nombre",
        "E1-08-02": "Evalua si el comando esta bien escrito",
    }

    assert seed.derive_question("E1-08-02", descripciones) == descripciones["E1-08-01"]


def test_question_es_none_sin_hermano_01():
    # Sin -01 no hay pregunta que derivar; el informe del seeder lo delata.
    assert seed.derive_question("E1-08-02", {"E1-08-02": "evalúa algo"}) is None


def test_question_es_none_en_nodos_que_no_evaluan():
    descripciones = {"E1-01": "cómic", "E1-02": "otro cómic"}

    # E1-02 termina en "-02" pero NO es un nodo de evaluación: es el segundo nodo del
    # bloque E1. La regex exige el patrón completo XX-NN-02.
    assert seed.derive_question("E1-02", descripciones) is None
    assert seed.derive_eval_instruction("E1-02", "otro cómic") is None


# ── integración sobre los CSV reales ────────────────────────────────────────────────


def test_los_csv_reales_no_dejan_ningun_nodo_de_evaluacion_incompleto():
    """El invariante que sostiene toda la evaluación: los 13 nodos `-02` tienen
    instrucción y pregunta. Si alguien edita los CSV y rompe el patrón, salta aquí."""
    nodes, _ = seed.load_rows()
    descripciones = {
        (r.get("id") or "").strip(): (r.get("description") or "").strip() for r in nodes
    }

    incompletos = []
    for row in nodes:
        node_id = (row.get("id") or "").strip()
        if not node_id:
            continue
        item, _ = seed._row_to_item(row, descripciones)
        evalua = item.get("eval_type") in ("open", "strict")
        if evalua and (not item.get("eval_instruction") or not item.get("question")):
            incompletos.append(node_id)

    assert incompletos == []


def test_sends_content_falso_solo_en_nodos_de_evaluacion_pura():
    # Los -02 no envían nada antes de esperar: generan el feedback DESPUÉS.
    assert seed.derive_sends_content(pauses=True, eval_type="open") is False
    assert seed.derive_sends_content(pauses=True, eval_type="strict") is False
    # R0-01 sí envía (la imagen del aviso legal) Y ADEMÁS espera.
    assert seed.derive_sends_content(pauses=True, eval_type="register") is True
    assert seed.derive_sends_content(pauses=False, eval_type=None) is True
