"""Borra el progreso de un alumno en `CourseStateTable`.

Uso:
    COURSE_STATE_TABLE=<nombre> AWS_REGION=eu-west-1 \
        python tools/reset-course-state.py --phone +34600111222

    python tools/reset-course-state.py --table <nombre> --phone +34600111222 --dry-run
    python tools/reset-course-state.py --table <nombre> --all      # solo en pruebas

## Cuándo hace falta

`current_order` es un número, no un `node_id`: apunta a una POSICIÓN de la secuencia. Si
el catálogo se re-siembra con la secuencia renumerada (p. ej. `CATALOG_VERSION = 5`, que
retira `R0-02` y desplaza todo una posición), los alumnos en vuelo quedan apuntando a un
nodo distinto del que estaban. Con alumnos reales eso exigiría una migración de posiciones;
mientras solo hay números de prueba, borrar y volver a empezar es más limpio y más barato.

No toca el catálogo ni ninguna otra tabla. Un alumno borrado vuelve a entrar como nuevo:
`identify_user` no lo encuentra y `register` lo da de alta en la posición 1.
"""

import argparse
import os
import sys

import boto3
from boto3.dynamodb.conditions import Attr


def _table(table_name: str):
    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return ddb.Table(table_name)


def listar(table_name: str) -> list[dict]:
    """Todos los alumnos de la tabla. Scan sin paginación fina: son decenas de ítems."""
    table = _table(table_name)
    items, kwargs = [], {"FilterExpression": Attr("PK").begins_with("USER#")}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def borrar(table_name: str, claves: list[dict], dry_run: bool) -> int:
    if dry_run or not claves:
        return 0
    table = _table(table_name)
    with table.batch_writer() as batch:
        for k in claves:
            batch.delete_item(Key=k)
    return len(claves)


def main() -> int:
    parser = argparse.ArgumentParser(description="Borra el progreso de alumnos del curso.")
    parser.add_argument("--table", default=os.environ.get("COURSE_STATE_TABLE"))
    parser.add_argument("--phone", action="append", help="Teléfono a borrar (repetible).")
    parser.add_argument("--all", action="store_true", help="Borra TODOS los alumnos.")
    parser.add_argument("--dry-run", action="store_true", help="Solo lista; no borra.")
    args = parser.parse_args()

    if not args.table:
        print("ERROR: falta --table o la env var COURSE_STATE_TABLE.", file=sys.stderr)
        return 2
    if not args.phone and not args.all:
        print("ERROR: indica --phone <tel> (repetible) o --all.", file=sys.stderr)
        return 2

    alumnos = listar(args.table)
    print(f"Tabla: {args.table} | alumnos encontrados: {len(alumnos)}")
    # Nunca se imprimen nombre, correo ni teléfono del adulto: son datos de contacto de
    # un adulto responsable de un menor (ver la nota de PII de F0).
    for a in alumnos:
        print(f"  {a['PK']}  order={a.get('current_order')}  waiting={a.get('waiting')}")

    if args.all:
        objetivo = [{"PK": a["PK"], "SK": a["SK"]} for a in alumnos]
    else:
        objetivo = [{"PK": f"USER#{p}", "SK": "STATE"} for p in args.phone]

    print(f"\nA borrar: {len(objetivo)} ítem(s)")
    if args.dry_run:
        print("--dry-run: no se borra nada.")
        return 0

    print(f"Borrados: {borrar(args.table, objetivo, dry_run=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
