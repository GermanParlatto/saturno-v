"""Tests del runner de migraciones: troceado de SQL, checksums e idempotencia.

Todo corre offline: `shared.db` se sustituye por dobles, así que nada de esto
toca AWS.
"""

from unittest.mock import MagicMock, patch

import pytest

from migrator import runner


# --------------------------------------------------------------- split_sql
def test_split_separa_sentencias():
    assert runner.split_sql("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_split_ignora_punto_y_coma_dentro_de_cadenas():
    """El caso que hace inservible un split(';') ingenuo: las descripciones de
    los nodos son prosa en español con puntuación arbitraria."""
    sql = "INSERT INTO nodes VALUES ('hola; adiós'); SELECT 2;"
    assert runner.split_sql(sql) == ["INSERT INTO nodes VALUES ('hola; adiós')", "SELECT 2"]


def test_split_respeta_apostrofes_escapados():
    sql = "INSERT INTO nodes VALUES ('las frases: ''vida = 100'', ''vida == 0''; ok');"
    partes = runner.split_sql(sql)
    assert len(partes) == 1
    assert "''vida = 100''" in partes[0]


def test_split_descarta_comentarios():
    sql = "-- comentario; con punto y coma\nSELECT 1;\n/* bloque; aqui */ SELECT 2;"
    assert runner.split_sql(sql) == ["SELECT 1", "SELECT 2"]


def test_split_respeta_dollar_quoting():
    sql = "CREATE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;"
    assert len(runner.split_sql(sql)) == 1


def test_split_acepta_ultima_sentencia_sin_punto_y_coma():
    assert runner.split_sql("SELECT 1") == ["SELECT 1"]


def test_split_ignora_vacio():
    assert runner.split_sql("\n\n;;  ;\n") == []


# ---------------------------------------------------------------- checksum
def test_checksum_estable_ante_saltos_de_linea_windows():
    assert runner.checksum("SELECT 1;\nSELECT 2;") == runner.checksum("SELECT 1;\r\nSELECT 2;")


def test_checksum_cambia_con_el_contenido():
    assert runner.checksum("SELECT 1;") != runner.checksum("SELECT 2;")


# --------------------------------------------------------------- discover
def test_discover_ordena_y_excluye_el_bootstrap(tmp_path):
    for nombre in ("001_b.sql", "000_migrations_table.sql", "003_a.sql", "002_c.sql"):
        (tmp_path / nombre).write_text("SELECT 1;", encoding="utf-8")
    assert [p.name for p in runner.discover(tmp_path)] == ["001_b.sql", "002_c.sql", "003_a.sql"]


# --------------------------------------------------------------------- run
def _prepara(tmp_path, aplicadas):
    (tmp_path / runner.BOOTSTRAP).write_text("CREATE TABLE schema_migrations ();", encoding="utf-8")
    (tmp_path / "001_schema.sql").write_text("CREATE TABLE nodes ();", encoding="utf-8")
    doble = MagicMock()
    doble.begin_transaction.return_value = "tx-1"
    doble.rows.return_value = [{"version": v, "checksum": c} for v, c in aplicadas.items()]
    return doble


def test_run_aplica_lo_pendiente(tmp_path):
    doble = _prepara(tmp_path, {})
    with patch.object(runner, "db", doble):
        resultado = runner.run(tmp_path)

    assert resultado == {"applied": ["001_schema.sql"], "skipped": []}
    doble.commit_transaction.assert_called_once_with("tx-1")
    doble.rollback_transaction.assert_not_called()


def test_run_es_no_op_si_ya_estaba_aplicada(tmp_path):
    """El criterio de aceptación: re-ejecutar los seeds no duplica nada."""
    contenido = "CREATE TABLE nodes ();"
    doble = _prepara(tmp_path, {"001_schema.sql": runner.checksum(contenido)})
    with patch.object(runner, "db", doble):
        resultado = runner.run(tmp_path)

    assert resultado == {"applied": [], "skipped": ["001_schema.sql"]}
    doble.begin_transaction.assert_not_called()


def test_run_aborta_si_una_migracion_aplicada_cambio(tmp_path):
    doble = _prepara(tmp_path, {"001_schema.sql": "checksum-viejo"})
    with patch.object(runner, "db", doble), pytest.raises(RuntimeError, match="ha cambiado"):
        runner.run(tmp_path)


def test_apply_revierte_la_transaccion_si_falla(tmp_path):
    doble = MagicMock()
    doble.begin_transaction.return_value = "tx-9"
    doble.execute.side_effect = RuntimeError("boom")

    with patch.object(runner, "db", doble), pytest.raises(RuntimeError, match="boom"):
        runner.apply_migration("001_schema.sql", "CREATE TABLE nodes ();")

    doble.rollback_transaction.assert_called_once_with("tx-9")
    doble.commit_transaction.assert_not_called()
