"""Siembra el catálogo del curso en `CourseCatalogTable` desde los CSV de `data/`.

Uso:
    CATALOG_TABLE=<nombre> AWS_REGION=eu-west-1 python tools/seed-course.py
    python tools/seed-course.py --table <nombre> [--course waku-l0] [--dry-run]

    python tools/seed-course.py --table <nombre> --check   # solo compara versiones
    python tools/seed-course.py --table <nombre> --force   # re-siembra sin comparar

Idempotente: escribe con `put_item` (sobrescribe), así dos ejecuciones dejan el mismo
estado. NO borra ítems que ya no estén en el CSV (fuera de alcance).

Los CSV traen el esquema crudo del documento. Aquí se DERIVAN, una sola vez y de forma
revisable, los campos corregidos del plan (`eval_type`, `sends_content`, `media_kind`).
El script imprime un informe de clasificación para revisar los casos ambiguos a ojo.

## Versionado del catálogo

El seeder escribe un ítem de control `CATALOG#<curso> / VERSION` con `CATALOG_VERSION`.
En cada ejecución compara la versión remota con la local:

  * iguales  → no escribe nada (el caso normal: un deploy que no toca el catálogo);
  * distinta → re-siembra el catálogo entero y actualiza el ítem de control.

Así el workflow de CI no necesita lógica propia: llama siempre al seeder y es el seeder
quien decide. Sustituye a la guarda anterior ("si la tabla tiene ítems, no toques nada"),
que dejaba el catálogo congelado para siempre tras la primera siembra: un cambio en las
derivaciones (p. ej. `eval_type=register` de R0-01) nunca habría llegado a producción.

REGLA que hace segura la re-siembra: las correcciones editoriales van EN ESTE FICHERO
(ver `EVAL_INSTRUCTIONS`) o en los CSV de `data/`, nunca editadas a mano en DynamoDB.
El catálogo es un artefacto derivado; la tabla no es la fuente de verdad de nada.
Al cambiar una derivación o un texto, SUBIR `CATALOG_VERSION` en el mismo commit.
"""

import argparse
import csv
import os
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NODES_CSV = DATA_DIR / "tb_nodes.csv"
FLOW_CSV = DATA_DIR / "tb_flow_sequence.csv"

# Subir SIEMPRE que cambien los CSV, las derivaciones o EVAL_INSTRUCTIONS.
#   1 → siembra inicial (F1)
#   2 → R0-01 pasa a eval_type="register" + eval_instruction de extracción de perfil
#   3 → F2: los gifs (R0-02, E1-05) se sirven como PNG -> media_kind "image", no "video"
CATALOG_VERSION = 3

# tb_nodes.type -> media_kind (tipo Meta).
#
# `gif` -> `image`: la Cloud API de Meta no acepta el formato .gif en NINGÚN tipo
# (`image` admite jpeg/png, `video` admite mp4/3gpp). Los dos gifs del curso (R0-02,
# nodo 2 de la secuencia, y E1-05) se sirven como PNG estático; `file_url` en
# data/tb_nodes.csv ya apunta a .png. El `type` se conserva en `gif` porque es la verdad
# editorial del nodo: lo que cambia es cómo se entrega, y eso es lo que expresa media_kind.
#
# `cheatsheet` -> `document`: PENDIENTE de la prueba real. Los 5 cheatsheets son .png, así
# que como `document` llegan de adjunto descargable en vez de verse en el chat. Cambiarlo
# a `image` es esta línea + un bump de CATALOG_VERSION.
MEDIA_KIND = {
    "comic": "image",
    "image": "image",
    "video": "video",
    "gif": "image",
    "cheatsheet": "document",
    "message": "text",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _parse_bool(s: str) -> bool:
    return (s or "").strip().upper() == "TRUE"


def derive_eval_type(logic: str, pauses: bool) -> str | None:
    """Clasifica el tipo de evaluación desde `logic`, sin depender de tildes.

    Devuelve None si el nodo no evalúa (no pausa).

    Un nodo que PAUSA sin declarar criterio en `Logic` no es una evaluación: es una
    captura de datos. Hoy el único caso es R0-01, la posición 1 de la secuencia, que
    recoge el consentimiento del adulto y el perfil. Se clasifica como `register` en
    lugar de dejarlo en `None` porque `None` caería en el `else` de `route_sequence`
    y rompería el arranque del curso para el 100% de los alumnos nuevos.
    """
    if not pauses:
        return None
    text = _strip_accents((logic or "").lower())
    if not text.strip():
        return "register"
    if "no existe un criterio" in text:
        return "open"
    if "si - nada" in text or "mensaje de agradecimiento" in text:
        return "ack"
    return "strict"


def derive_sends_content(pauses: bool, eval_type: str | None) -> bool:
    """Los nodos de evaluación pura (open/strict) generan el feedback DESPUÉS de la
    respuesta: no envían nada antes de esperar. El resto sí envía su contenido.

    `register` NO entra en la excepción: R0-01 sí envía (la imagen con el aviso legal
    y la petición de datos) y ADEMÁS espera respuesta.
    """
    return not (pauses and eval_type in ("open", "strict"))


# Instrucciones para el LLM, separadas de `description` (que es contenido a enviar).
# Los CSV de origen no distinguen ambos usos, así que la separación se hace aquí, a
# mano y revisable, en vez de derivarse. Solo los nodos presentes en este dict llevan
# `eval_instruction`; el resto queda pendiente de la pasada editorial de F4.
EVAL_INSTRUCTIONS = {
    "R0-01": (
        "Extrae de la respuesta del usuario estos cuatro campos: student_name (nombre "
        "del alumno), adult_name (nombre completo del adulto responsable), adult_email "
        "(correo del adulto) y adult_phone (teléfono del adulto). El usuario es un menor "
        "de 10 a 14 años: escribirá en lenguaje natural, en cualquier orden y puede "
        "repartir los datos en varios mensajes. NO evalúes ni corrijas nada. Si falta "
        "algún campo o el correo no tiene formato válido, pide SOLO lo que falte, en una "
        "burbuja corta y en la voz de Spoky, sin repetir los datos ya recibidos."
    ),
}


def _row_to_item(row: dict, pk_course: str) -> tuple[dict, dict]:
    """Convierte una fila del CSV en el ítem DynamoDB + un resumen para el informe."""
    node_id = row["id"].strip()
    type_ = (row["type"] or "").strip()
    pauses = _parse_bool(row["pauses"])
    eval_type = derive_eval_type(row.get("Logic", ""), pauses)
    sends_content = derive_sends_content(pauses, eval_type)
    media_kind = MEDIA_KIND.get(type_)

    item = {
        "PK": f"NODE#{node_id}",
        "SK": "META",
        "node_id": node_id,
        "type": type_,
        "pauses": pauses,
        "sends_content": sends_content,
    }
    optional = {
        "function": (row.get("function") or "").strip(),
        "description": (row.get("description") or "").strip(),
        "output": (row.get("Output") or "").strip(),
        "logic": (row.get("Logic") or "").strip(),
        "file_url": (row.get("file_url") or "").strip(),
        "eval_type": eval_type,
        "media_kind": media_kind,
        # Solo los nodos de EVAL_INSTRUCTIONS; el resto, pendiente de la pasada de F4.
        "eval_instruction": EVAL_INSTRUCTIONS.get(node_id),
    }
    for k, v in optional.items():
        if v not in (None, ""):
            item[k] = v

    summary = {
        "node_id": node_id,
        "type": type_,
        "pauses": pauses,
        "eval_type": eval_type,
        "sends_content": sends_content,
        "media_kind": media_kind,
    }
    return item, summary


def load_rows() -> tuple[list[dict], list[dict]]:
    # utf-8-sig elimina el BOM del header de los CSV exportados.
    with open(NODES_CSV, encoding="utf-8-sig", newline="") as f:
        nodes = list(csv.DictReader(f))
    with open(FLOW_CSV, encoding="utf-8-sig", newline="") as f:
        flow = list(csv.DictReader(f))
    return nodes, flow


def print_report(summaries: list[dict], nodes: list[dict], flow: list[dict]) -> None:
    node_ids = {r["id"].strip() for r in nodes}
    flow_ids = {r["node_id"].strip() for r in flow}

    print("\n=== Clasificación de nodos ===")
    print(f"{'node_id':<12} {'type':<11} {'pausa':<6} {'eval_type':<9} {'sends':<6} media_kind")
    for s in summaries:
        print(
            f"{s['node_id']:<12} {s['type']:<11} {str(s['pauses']):<6} "
            f"{str(s['eval_type']):<9} {str(s['sends_content']):<6} {s['media_kind']}"
        )

    ambiguous = [s["node_id"] for s in summaries if s["pauses"] and s["eval_type"] is None]
    acks = [s["node_id"] for s in summaries if s["eval_type"] == "ack"]
    registers = [s["node_id"] for s in summaries if s["eval_type"] == "register"]
    # Nodos que evalúan pero aún sin instrucción propia: usarán `description` como
    # fallback en F4. Es el TODO editorial pendiente, aquí cuantificado.
    sin_instruccion = [
        s["node_id"]
        for s in summaries
        if s["eval_type"] in ("open", "strict") and s["node_id"] not in EVAL_INSTRUCTIONS
    ]
    orphan_defs = sorted(node_ids - flow_ids)  # definidos pero fuera de la secuencia
    missing_defs = sorted(flow_ids - node_ids)  # en la secuencia pero sin definición

    print("\n=== Revisar a ojo ===")
    print(f"Pausan SIN eval_type (revisar): {ambiguous or '—'}  <-- caerían en el else")
    print(f"eval_type=register (alta):      {registers or '—'}")
    print(f"eval_type=ack (acuse simple):   {acks or '—'}")
    print(f"Evalúan SIN eval_instruction:   {len(sin_instruccion)} nodos (fallback a description)")
    print(f"Nodos definidos NO en secuencia: {orphan_defs or '—'}")
    print(f"Nodos en secuencia SIN definir:  {missing_defs or '—'}  <-- ¡romperían el curso!")


def _version_key(course_id: str) -> dict[str, str]:
    """Ítem de control. PK propia (`CATALOG#…`): no aparece ni en la Query de la
    secuencia (`FLOW#…`) ni en los BatchGet de nodos (`NODE#…`), así que el catálogo
    en runtime lo ignora sin cambio alguno en `src/course/catalog.py`."""
    return {"PK": f"CATALOG#{course_id}", "SK": "VERSION"}


def get_remote_version(table_name: str, course_id: str) -> int | None:
    """Versión sembrada hoy en la tabla. `None` = tabla virgen o sin ítem de control
    (catálogo sembrado antes de existir el versionado: se trata como desactualizado)."""
    table = _table(table_name)
    try:
        item = table.get_item(Key=_version_key(course_id)).get("Item")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    return int(item["version"]) if item else None


def _table(table_name: str):
    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return ddb.Table(table_name)


def seed(table_name: str, course_id: str, dry_run: bool, force: bool = False) -> None:
    nodes, flow = load_rows()
    items: list[dict] = []
    summaries: list[dict] = []

    for row in nodes:
        if not (row.get("id") or "").strip():
            continue
        item, summary = _row_to_item(row, course_id)
        items.append(item)
        summaries.append(summary)

    for row in flow:
        order = int(row["order"])
        items.append(
            {
                "PK": f"FLOW#{course_id}",
                "SK": f"ORD#{order:06d}",
                "node_id": row["node_id"].strip(),
            }
        )

    print_report(summaries, nodes, flow)

    print(f"\n=== Escritura ===\nTabla: {table_name} | curso: {course_id} | ítems: {len(items)}")
    if dry_run:
        print(f"--dry-run: no se escribe nada. (versión local: {CATALOG_VERSION})")
        return

    remote = get_remote_version(table_name, course_id)
    print(
        f"Versión remota: {remote if remote is not None else '(ninguna)'} | local: {CATALOG_VERSION}"
    )
    if remote == CATALOG_VERSION and not force:
        print("Catálogo al día; no se escribe nada. (usa --force para re-sembrar)")
        return

    table = _table(table_name)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
        # El ítem de control va EL ÚLTIMO: si la escritura del catálogo falla a medias,
        # la versión remota no avanza y el siguiente intento vuelve a sembrar entero.
        batch.put_item(
            Item={
                **_version_key(course_id),
                "version": CATALOG_VERSION,
                "items": len(items),
                "seeded_at": datetime.now(UTC).isoformat(),
            }
        )
    print(f"Hecho: catálogo en versión {CATALOG_VERSION}. (re-ejecutar deja el mismo estado)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Siembra el catálogo del curso en DynamoDB.")
    parser.add_argument("--table", default=os.environ.get("CATALOG_TABLE"))
    parser.add_argument("--course", default=os.environ.get("COURSE_ID", "waku-l0"))
    parser.add_argument("--dry-run", action="store_true", help="No escribe; solo el informe.")
    parser.add_argument(
        "--force", action="store_true", help="Re-siembra aunque la versión coincida."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Solo compara versiones y sale. Exit 0 al día, 3 si hay migración pendiente.",
    )
    args = parser.parse_args()

    if not args.table and not args.dry_run:
        print("ERROR: falta --table o la env var CATALOG_TABLE.", file=sys.stderr)
        return 2

    if args.check:
        remote = get_remote_version(args.table, args.course)
        al_dia = remote == CATALOG_VERSION
        print(f"local={CATALOG_VERSION} remota={remote} al_dia={str(al_dia).lower()}")
        # Exit code propio (3, no 1) para distinguir "hay migración pendiente" de un
        # fallo real del script — el workflow los trata de forma distinta.
        return 0 if al_dia else 3

    seed(args.table or "(dry-run)", args.course, args.dry_run, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
