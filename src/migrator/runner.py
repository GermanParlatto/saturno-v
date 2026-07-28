"""Aplicación de migraciones SQL sobre Aurora vía Data API.

Reglas del diseño:

  * Cada migración se aplica DENTRO de una transacción, y la fila de
    `schema_migrations` se inserta en esa misma transacción. O se aplica entera
    y queda registrada, o no pasa ninguna de las dos cosas.
  * Una migración ya aplicada cuyo contenido ha cambiado ABORTA el proceso. Es
    la señal de que alguien editó un fichero ya ejecutado, que es justo como los
    entornos empiezan a divergir en silencio.
  * Re-ejecutar sin cambios es un no-op.
"""

import hashlib
import re
from pathlib import Path

from shared import db
from shared.observability import logger

# Los .sql viajan DENTRO de src/ porque el CodeUri de SAM es ../src: un
# directorio de migraciones en la raíz del repo no existiría en el artefacto
# desplegado y el migrador no encontraría nada que aplicar.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Se aplica siempre y aparte: crea la propia tabla de registro.
BOOTSTRAP = "000_migrations_table.sql"


def split_sql(text: str) -> list[str]:
    """Parte un script en sentencias sueltas (el Data API solo acepta una).

    Un `text.split(";")` sería incorrecto aquí: las descripciones de los nodos
    son prosa en español llena de apóstrofes, y un punto y coma dentro de una
    cadena partiría la sentencia por la mitad. Hay que respetar cadenas,
    dollar-quoting y comentarios.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    length = len(text)

    while i < length:
        char = text[i]
        rest = text[i:]

        # Comentario de línea: se descarta hasta el salto.
        if rest.startswith("--"):
            end = text.find("\n", i)
            i = length if end == -1 else end
            continue

        # Comentario de bloque.
        if rest.startswith("/*"):
            end = text.find("*/", i + 2)
            i = length if end == -1 else end + 2
            continue

        # Cadena literal: '' es un apóstrofe escapado, no el fin de la cadena.
        if char == "'":
            current.append(char)
            i += 1
            while i < length:
                if text[i] == "'":
                    if i + 1 < length and text[i + 1] == "'":
                        current.append("''")
                        i += 2
                        continue
                    current.append("'")
                    i += 1
                    break
                current.append(text[i])
                i += 1
            continue

        # Dollar-quoting: $$...$$ o $tag$...$tag$ (cuerpos de funciones).
        if char == "$":
            match = re.match(r"\$[A-Za-z_0-9]*\$", rest)
            if match:
                tag = match.group(0)
                end = text.find(tag, i + len(tag))
                stop = length if end == -1 else end + len(tag)
                current.append(text[i:stop])
                i = stop
                continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def checksum(text: str) -> str:
    """Hash del contenido, normalizando saltos de línea para que un checkout en
    Windows no invalide todas las migraciones."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """Migraciones a aplicar, en orden lexicográfico y sin el bootstrap."""
    return sorted(p for p in directory.glob("*.sql") if p.name != BOOTSTRAP)


def applied_versions() -> dict[str, str]:
    response = db.execute("SELECT version, checksum FROM schema_migrations")
    return {row["version"]: row["checksum"] for row in db.rows(response)}


def ensure_bootstrap(directory: Path = MIGRATIONS_DIR) -> None:
    """Crea schema_migrations. Es IF NOT EXISTS: re-aplicarlo es inocuo."""
    for statement in split_sql((directory / BOOTSTRAP).read_text(encoding="utf-8")):
        db.execute(statement)


def apply_migration(version: str, text: str) -> None:
    """Aplica una migración y la registra, todo en la misma transacción."""
    statements = split_sql(text)
    transaction_id = db.begin_transaction()
    try:
        for statement in statements:
            db.execute(statement, transaction_id=transaction_id)
        db.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (:version, :checksum)",
            {"version": version, "checksum": checksum(text)},
            transaction_id=transaction_id,
        )
        db.commit_transaction(transaction_id)
    except Exception:
        db.rollback_transaction(transaction_id)
        logger.exception("Migración fallida, transacción revertida", extra={"version": version})
        raise
    logger.info("Migración aplicada", extra={"version": version, "sentencias": len(statements)})


def run(directory: Path = MIGRATIONS_DIR) -> dict[str, list[str]]:
    """Aplica lo que falte. Devuelve qué se aplicó y qué se saltó."""
    ensure_bootstrap(directory)
    already = applied_versions()

    applied: list[str] = []
    skipped: list[str] = []

    for path in discover(directory):
        version = path.name
        text = path.read_text(encoding="utf-8")

        if version in already:
            if already[version] != checksum(text):
                raise RuntimeError(
                    f"La migración '{version}' ya se aplicó pero su contenido ha cambiado. "
                    "No edites una migración aplicada: crea una nueva."
                )
            skipped.append(version)
            continue

        apply_migration(version, text)
        applied.append(version)

    logger.info("Migraciones al día", extra={"aplicadas": len(applied), "saltadas": len(skipped)})
    return {"applied": applied, "skipped": skipped}
