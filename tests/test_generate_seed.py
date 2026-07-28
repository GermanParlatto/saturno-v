"""Tests del generador de seeds.

Cubren las dos cosas que romperían la carga en silencio: el escapado de
apóstrofes (la prosa del curso está llena) y la regla de stage/mission, donde
"vacío" y "cero" NO son lo mismo.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from generate_seed import etapa_desde_id, lit, normaliza_metadata  # noqa: E402


# --------------------------------------------------------------------- lit
def test_lit_escapa_apostrofes_duplicandolos():
    assert lit("las frases: 'vida = 100'") == "'las frases: ''vida = 100'''"


def test_lit_none_y_vacio_son_null():
    assert lit(None) == "NULL"
    assert lit("") == "NULL"


def test_lit_booleanos():
    assert lit(True) == "TRUE"
    assert lit(False) == "FALSE"


def test_lit_enteros_sin_comillas():
    assert lit(0) == "0"
    assert lit(70) == "70"


def test_lit_conserva_saltos_de_linea():
    """El campo Logic trae saltos embebidos ('Si - Nada\\nNo - ...')."""
    assert lit("Si - Nada\nNo - Gracias") == "'Si - Nada\nNo - Gracias'"


# ---------------------------------------------------------- etapa_desde_id
@pytest.mark.parametrize(
    ("node_id", "esperado"),
    [
        ("E0-01", 0),
        ("E1-01-01", 1),
        ("E2-03-02", 2),
        ("E3-09", 3),
        ("E4-07-01", 4),
        ("EF-02", 5),
    ],
)
def test_etapa_desde_el_prefijo(node_id, esperado):
    assert etapa_desde_id(node_id) == esperado


def test_los_nodos_r0_no_tienen_etapa():
    """R0-* son registro/consentimiento, no una etapa del curso: NULL, no 0.
    Confundirlos con la etapa 0 falsearía cualquier consulta por etapa."""
    assert etapa_desde_id("R0-01") is None
    assert etapa_desde_id("R0-02") is None


# ------------------------------------------------------- normaliza_metadata
def test_metadata_vacia_es_objeto_vacio():
    assert normaliza_metadata(None) == "{}"
    assert normaliza_metadata("") == "{}"


def test_metadata_json_valido_se_conserva():
    assert normaliza_metadata('{"panels":5}') == '{"panels": 5}'


def test_metadata_invalida_no_rompe_el_sql(capsys):
    """Un valor corrupto degrada a '{}' en vez de generar SQL que peta al
    hacer el CAST a jsonb."""
    assert normaliza_metadata("esto no es json") == "{}"
    assert "aviso" in capsys.readouterr().err


# --------------------------------------------- el SQL generado y versionado
MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "src" / "migrations"


def test_el_seed_generado_tiene_los_70_nodos():
    sql = (MIGRATIONS / "003_seed_nodes.sql").read_text(encoding="utf-8")
    assert len([ln for ln in sql.splitlines() if ln.startswith("    ('")]) == 70
    assert "ON CONFLICT (id) DO UPDATE" in sql


def test_el_seed_de_flujo_tiene_las_70_posiciones():
    sql = (MIGRATIONS / "004_seed_flow_sequence.sql").read_text(encoding="utf-8")
    assert len([ln for ln in sql.splitlines() if ln.startswith("    (")]) == 70
    assert "ON CONFLICT (id) DO UPDATE" in sql
