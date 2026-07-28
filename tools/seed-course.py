"""Siembra el catálogo del curso en `CourseCatalogTable` desde los CSV de `data/`.

Uso:
    CATALOG_TABLE=<nombre> AWS_REGION=eu-west-1 python tools/seed-course.py
    python tools/seed-course.py --table <nombre> [--course waku-l0] [--dry-run]

Idempotente: escribe con `put_item` (sobrescribe), así dos ejecuciones dejan el mismo
estado. NO borra ítems que ya no estén en el CSV (fuera de alcance).

Los CSV traen el esquema crudo del documento. Aquí se DERIVAN, una sola vez y de forma
revisable, los campos corregidos del plan (`eval_type`, `sends_content`, `media_kind`).
El script imprime un informe de clasificación para revisar los casos ambiguos a ojo.
"""

import argparse
import csv
import os
import sys
import unicodedata
from pathlib import Path

import boto3

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NODES_CSV = DATA_DIR / "tb_nodes.csv"
FLOW_CSV = DATA_DIR / "tb_flow_sequence.csv"

# tb_nodes.type -> media_kind (tipo Meta). Meta NO tiene tipo `gif`: un .gif se entrega
# como video/mp4 (verificar el formato real de R0-02 en Contabo, ver F2).
MEDIA_KIND = {
    "comic": "image",
    "image": "image",
    "video": "video",
    "gif": "video",
    "cheatsheet": "document",
    "message": "text",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _parse_bool(s: str) -> bool:
    return (s or "").strip().upper() == "TRUE"


def derive_eval_type(logic: str, pauses: bool) -> str | None:
    """Clasifica el tipo de evaluación desde `logic`, sin depender de tildes.

    Devuelve None si el nodo no evalúa (no pausa) o si pausa sin criterio (ambiguo:
    se marca en el informe para revisión — hoy solo R0-01, el registro).
    """
    if not pauses:
        return None
    text = _strip_accents((logic or "").lower())
    if not text.strip():
        return None
    if "no existe un criterio" in text:
        return "open"
    if "si - nada" in text or "mensaje de agradecimiento" in text:
        return "ack"
    return "strict"


def derive_sends_content(pauses: bool, eval_type: str | None) -> bool:
    """Los nodos de evaluación pura (open/strict) generan el feedback DESPUÉS de la
    respuesta: no envían nada antes de esperar. El resto sí envía su contenido."""
    return not (pauses and eval_type in ("open", "strict"))


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
        # eval_instruction se rellena en una pasada editorial posterior.
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
    orphan_defs = sorted(node_ids - flow_ids)  # definidos pero fuera de la secuencia
    missing_defs = sorted(flow_ids - node_ids)  # en la secuencia pero sin definición

    print("\n=== Revisar a ojo ===")
    print(f"Pausan SIN eval_type (revisar): {ambiguous or '—'}")
    print(f"eval_type=ack (acuse simple):   {acks or '—'}")
    print(f"Nodos definidos NO en secuencia: {orphan_defs or '—'}")
    print(f"Nodos en secuencia SIN definir:  {missing_defs or '—'}  <-- ¡romperían el curso!")


def seed(table_name: str, course_id: str, dry_run: bool) -> None:
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
        print("--dry-run: no se escribe nada.")
        return

    table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1")).Table(
        table_name
    )
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    print("Hecho. (idempotente: re-ejecutar deja el mismo estado)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Siembra el catálogo del curso en DynamoDB.")
    parser.add_argument("--table", default=os.environ.get("CATALOG_TABLE"))
    parser.add_argument("--course", default=os.environ.get("COURSE_ID", "waku-l0"))
    parser.add_argument("--dry-run", action="store_true", help="No escribe; solo el informe.")
    args = parser.parse_args()

    if not args.table and not args.dry_run:
        print("ERROR: falta --table o la env var CATALOG_TABLE.", file=sys.stderr)
        return 2

    seed(args.table or "(dry-run)", args.course, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
