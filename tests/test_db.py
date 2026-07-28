"""Tests de la conversión de tipos del Data API (shared/db.py).

Es la parte puntillosa del cliente: el Data API no acepta valores Python
directamente, y equivocarse aquí produce errores de tipo en runtime lejos de la
causa. Nada de esto llama a AWS.
"""

from shared import db


def test_none_viaja_como_isnull():
    assert db.to_param("x", None) == {"name": "x", "value": {"isNull": True}}


def test_bool_no_se_convierte_en_entero():
    """bool es subclase de int en Python: si el isinstance de int va primero,
    True acaba guardado como 1."""
    assert db.to_param("p", True) == {"name": "p", "value": {"booleanValue": True}}
    assert db.to_param("p", False) == {"name": "p", "value": {"booleanValue": False}}


def test_enteros_y_flotantes():
    assert db.to_param("n", 70) == {"name": "n", "value": {"longValue": 70}}
    assert db.to_param("n", 1.5) == {"name": "n", "value": {"doubleValue": 1.5}}


def test_texto_con_acentos_no_se_escapa_a_ascii():
    param = db.to_param("s", "Bitácora de Spoky")
    assert param["value"]["stringValue"] == "Bitácora de Spoky"


def test_dict_viaja_como_json():
    param = db.to_param("m", {"panels": 5})
    assert param["value"]["stringValue"] == '{"panels": 5}'


def test_rows_empareja_columnas_con_valores():
    respuesta = {
        "columnMetadata": [{"name": "id"}, {"name": "stage"}, {"name": "pauses"}],
        "records": [
            [{"stringValue": "R0-01"}, {"isNull": True}, {"booleanValue": True}],
            [{"stringValue": "E1-01"}, {"longValue": 1}, {"booleanValue": False}],
        ],
    }
    assert db.rows(respuesta) == [
        {"id": "R0-01", "stage": None, "pauses": True},
        {"id": "E1-01", "stage": 1, "pauses": False},
    ]


def test_rows_con_resultado_vacio():
    assert db.rows({"columnMetadata": [{"name": "n"}], "records": []}) == []
