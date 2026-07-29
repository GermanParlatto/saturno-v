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
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NODES_CSV = DATA_DIR / "tb_nodes.csv"
FLOW_CSV = DATA_DIR / "tb_flow_sequence.csv"

# Subir SIEMPRE que cambien los CSV, las derivaciones o EVAL_INSTRUCTIONS.
#   1 → siembra inicial (F1)
#   2 → R0-01 pasa a eval_type="register" + eval_instruction de extracción de perfil
#   3 → F2: los gifs (R0-02, E1-05) se sirven como PNG -> media_kind "image", no "video"
#   4 → F4: eval_instruction derivado en los 13 nodos -02 + `question` (la pregunta que
#           planteó su hermano -01, sin la cual el evaluador juzga a ciegas)
#   5 → Correcciones de la primera pasada real (claude/PLAN-fix-flujo-real.md):
#       R0-02 sale de la secuencia (pausa muda que atascaba el curso), la secuencia se
#       numera por posición de fila, y las derivaciones de sends_content / instrucción /
#       pregunta dejan de depender del sufijo -02 (E0-02-01 se escapaba de las tres)
CATALOG_VERSION = 5

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


def derive_sends_content(pauses: bool, file_url: str) -> bool:
    """Un nodo que PAUSA y no tiene fichero no tiene nada que enviar antes de esperar.

    Su `description` es la instrucción para el evaluador («Evalúa si el comando está
    bien escrito»), no contenido: el runner la convertiría en un mensaje y le mandaría
    al alumno la nota del guionista. Pasó en producción con `E0-02-01`, que por llamarse
    `-01` se escapaba del criterio anterior — basado en `eval_type in (open, strict)` —
    y recibió «Este es un nuevo objetivo: evalúa la respuesta del usuario…».

    El criterio pasa a ser el dato observable (¿hay fichero que mandar?) en vez del tipo
    de evaluación, que era una aproximación. `R0-01` sigue enviando: pausa, pero TIENE
    `file_url` (la imagen con el aviso legal y la petición de datos).
    """
    return not (pauses and not (file_url or "").strip())


# El curso usa un patrón regular de tres nodos por interacción:
#
#   E1-08      contenido (vídeo/cómic), no pausa
#   E1-08-01   LA PREGUNTA («…que ahora escriba su nombre»), no pausa
#   E1-08-02   LA EVALUACIÓN («Evalúa si el comando está bien escrito»), PAUSA
#
# Las dos derivaciones siguientes se basaban en el sufijo `-02`. Ya no: `E0-02-01` es un
# nodo de evaluación con nomenclatura de pregunta y se escapaba de ambas, así que
# evaluaba sin instrucción y sin saber qué se había preguntado. El criterio pasa a ser
# «pausa y no tiene fichero» (= es un nodo de evaluación), y la pregunta se toma del
# nodo ANTERIOR EN LA SECUENCIA en vez del hermano `-01` por nombre.
#
# Verificado sobre los 70 nodos: para los 13 `XX-NN-02` el nodo anterior en la secuencia
# ES su `-01` (ORD 8←7, 14←13, 19←18, 24←23, 29←28, 33←32, 37←36, 43←42, 46←45, 51←50,
# 57←56, 62←61, 68←67 en la numeración previa), así que la regla nueva es equivalente
# donde ya funcionaba y además cubre `E0-02-01`.


def derive_eval_instruction(node_id: str, description: str, es_evaluacion: bool) -> str | None:
    """Instrucción para el LLM evaluador.

    En los nodos de evaluación la `description` YA está redactada como instrucción
    («Evalúa si…», «Interpreta la respuesta y refuerza…»), así que promocionarla al
    campo dedicado es mover un dato, no redactar uno nuevo. `EVAL_INSTRUCTIONS` tiene
    precedencia para poder afinar un nodo sin tocar el CSV.
    """
    if node_id in EVAL_INSTRUCTIONS:
        return EVAL_INSTRUCTIONS[node_id]
    if es_evaluacion:
        return (description or "").strip() or None
    return None


def derive_question(node_id: str, anterior: dict[str, str], es_evaluacion: bool) -> str | None:
    """La pregunta que este nodo está evaluando: la `description` del nodo que le
    precede en la secuencia.

    Sin esto el evaluador juzga a ciegas — recibe «evalúa si el comando está bien
    escrito» sin saber QUÉ comando se pidió.

    Es un respaldo: en runtime tiene precedencia `UserState.last_question`, el texto
    literal que se envió al alumno. Este campo guarda la acotación de guion, que puede
    estar en imperativo y no es lo que el alumno leyó.
    """
    if not es_evaluacion:
        return None
    return (anterior.get(node_id) or "").strip() or None


# Instrucciones para el LLM, separadas de `description` (que es contenido a enviar).
# Solo para nodos que NO siguen el patrón `-02` o que necesitan un texto distinto del
# de su `description`. Hoy solo R0-01, que es un alta, no una evaluación.
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


def _row_to_item(row: dict, anterior: dict[str, str]) -> tuple[dict, dict]:
    """Convierte una fila del CSV en el ítem DynamoDB + un resumen para el informe.

    `anterior` mapea node_id -> description del nodo que le PRECEDE en la secuencia:
    de ahí sale la pregunta que un nodo de evaluación está juzgando.
    """
    node_id = row["id"].strip()
    type_ = (row["type"] or "").strip()
    description = (row.get("description") or "").strip()
    pauses = _parse_bool(row["pauses"])
    file_url = (row.get("file_url") or "").strip()
    eval_type = derive_eval_type(row.get("Logic", ""), pauses)
    sends_content = derive_sends_content(pauses, file_url)
    # Un nodo de evaluación es el que pausa sin nada que enviar: lo único que hace es
    # esperar la respuesta y juzgarla. `R0-01` pausa pero envía su imagen, así que no
    # entra (y no lo necesita: su instrucción está en EVAL_INSTRUCTIONS).
    es_evaluacion = pauses and not sends_content
    media_kind = MEDIA_KIND.get(type_)
    eval_instruction = derive_eval_instruction(node_id, description, es_evaluacion)
    question = derive_question(node_id, anterior, es_evaluacion)

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
        "description": description,
        "output": (row.get("Output") or "").strip(),
        "logic": (row.get("Logic") or "").strip(),
        "file_url": (row.get("file_url") or "").strip(),
        "eval_type": eval_type,
        "media_kind": media_kind,
        "eval_instruction": eval_instruction,
        # La pregunta que este nodo evalúa (del nodo anterior en la secuencia).
        "question": question,
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
        "eval_instruction": eval_instruction,
        "question": question,
        "es_evaluacion": es_evaluacion,
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
    # Los dos deben salir a CERO. Si no, la evaluación se haría a ciegas (sin saber qué
    # se preguntó) o sin instrucción. El criterio es `es_evaluacion` (pausa sin nada que
    # enviar), no el `eval_type`: E0-02-01 es `ack` y necesitaba las dos cosas.
    sin_instruccion = [
        s["node_id"] for s in summaries if s["es_evaluacion"] and not s["eval_instruction"]
    ]
    sin_pregunta = [s["node_id"] for s in summaries if s["es_evaluacion"] and not s["question"]]
    # Un nodo que pausa y ENVÍA texto generado le mandaría al alumno la nota de guion en
    # vez de contenido: es exactamente el fallo de E0-02-01 en la primera pasada real.
    pausa_enviando_texto = [
        s["node_id"]
        for s in summaries
        if s["pauses"] and s["sends_content"] and s["media_kind"] == "text"
    ]
    orphan_defs = sorted(node_ids - flow_ids)  # definidos pero fuera de la secuencia
    missing_defs = sorted(flow_ids - node_ids)  # en la secuencia pero sin definición

    print("\n=== Revisar a ojo ===")
    print(f"Pausan SIN eval_type (revisar): {ambiguous or '—'}  <-- caerían en el else")
    print(f"eval_type=register (alta):      {registers or '—'}")
    print(f"eval_type=ack (acuse simple):   {acks or '—'}")
    print(f"Evalúan SIN eval_instruction:   {sin_instruccion or '—'}  <-- debe ser —")
    print(f"Evalúan SIN pregunta derivada:  {sin_pregunta or '—'}  <-- debe ser —")
    print(f"Pausan enviando texto generado: {pausa_enviando_texto or '—'}  <-- debe ser —")
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


def build_sequence(flow: list[dict]) -> list[str]:
    """Secuencia de node_ids en orden, numerada por POSICIÓN DE FILA.

    La columna `order` del CSV se ignora deliberadamente. Al retirar un nodo (R0-02) sin
    renumerar quedaría un hueco, y `catalog.get_node_at()` devuelve `None` para una
    posición inexistente: el runner lo leería como fin de curso y graduaría en silencio
    a todos los alumnos en el nodo 2. Numerando por posición, un borrado en el CSV no
    puede producir un hueco.
    """
    return [nid for r in flow if (nid := (r.get("node_id") or "").strip())]


def purge_stale_flow(table_name: str, course_id: str, length: int) -> int:
    """Borra los `ORD#` que sobran cuando la secuencia se acorta. Devuelve cuántos.

    El seeder escribe con `put_item`, que sobrescribe pero nunca borra. Al pasar de 70 a
    69 posiciones, `ORD#000070` sobreviviría apuntando al nodo que estaba ahí antes y el
    curso repetiría el último nodo en vez de terminar.
    """
    table = _table(table_name)
    sobrantes = []
    kwargs = {
        "KeyConditionExpression": Key("PK").eq(f"FLOW#{course_id}")
        & Key("SK").gt(f"ORD#{length:06d}"),
        "ProjectionExpression": "PK, SK",
    }
    while True:
        resp = table.query(**kwargs)
        sobrantes.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if sobrantes:
        with table.batch_writer() as batch:
            for it in sobrantes:
                batch.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
    return len(sobrantes)


def seed(table_name: str, course_id: str, dry_run: bool, force: bool = False) -> None:
    nodes, flow = load_rows()
    items: list[dict] = []
    summaries: list[dict] = []

    secuencia = build_sequence(flow)

    # Índice previo: la pregunta que evalúa un nodo es la description del nodo que le
    # PRECEDE en la secuencia, así que hace falta la secuencia ya construida.
    descripciones = {
        (r.get("id") or "").strip(): (r.get("description") or "").strip() for r in nodes
    }
    anterior = {
        nid: descripciones.get(secuencia[i - 1], "") for i, nid in enumerate(secuencia) if i > 0
    }

    for row in nodes:
        if not (row.get("id") or "").strip():
            continue
        item, summary = _row_to_item(row, anterior)
        items.append(item)
        summaries.append(summary)

    for order, node_id in enumerate(secuencia, start=1):
        items.append(
            {
                "PK": f"FLOW#{course_id}",
                "SK": f"ORD#{order:06d}",
                "node_id": node_id,
            }
        )

    print_report(summaries, nodes, flow)

    duplicados = sorted({n for n in secuencia if secuencia.count(n) > 1})
    print(f"\n=== Secuencia ===\nPosiciones: 1..{len(secuencia)} (contiguas por construcción)")
    print(f"Primeros 5: {secuencia[:5]}")
    print(f"node_id repetidos en la secuencia: {duplicados or '—'}  <-- debe ser —")

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

    # La purga va DESPUÉS de escribir y ANTES del ítem de control: si falla, la versión
    # remota no avanza y el siguiente intento repite. Al revés (purgar primero) habría
    # un instante con la secuencia truncada y sin reescribir.
    borrados = purge_stale_flow(table_name, course_id, len(secuencia))
    print(f"Purga de posiciones sobrantes: {borrados} ítem(s) `ORD#` borrado(s)")

    # El ítem de control va EL ÚLTIMO: si la escritura del catálogo falla a medias, la
    # versión remota no avanza y el siguiente intento vuelve a sembrar entero.
    table.put_item(
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
