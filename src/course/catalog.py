"""Catálogo del curso: definición estática cacheada por contenedor.

El catálogo (definiciones de nodo + secuencia) es estático: ~70 ítems que solo cambian
en un deploy. En vez de leer DynamoDB en cada mensaje, en el primer acceso de un
contenedor Lambda se carga TODO a RAM (una Query de la secuencia + un BatchGetItem de las
definiciones) y a partir de ahí los lookups son en memoria: latencia de un dict con la
editabilidad de una tabla.

Lambda reutiliza el contenedor entre invocaciones, así que la caché sobrevive a varios
mensajes. Si el contenedor es nuevo, se vuelve a cargar (coste una vez por contenedor).
"""

import os

import boto3
from boto3.dynamodb.conditions import Key

from .models import CourseNode

_COURSE_ID = os.environ.get("COURSE_ID", "waku-l0")

# Caché a nivel de módulo (una por contenedor). `None` = aún no cargada.
_nodes_by_id: dict[str, CourseNode] | None = None
_order_to_node_id: dict[int, str] | None = None


def _catalog_table():
    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return ddb, ddb.Table(os.environ["CATALOG_TABLE"])


def _load() -> None:
    """Carga la secuencia y las definiciones a RAM. Idempotente: no re-lee si ya hay caché."""
    global _nodes_by_id, _order_to_node_id
    if _nodes_by_id is not None:
        return

    ddb, table = _catalog_table()

    # 1) Secuencia: FLOW#<curso> / ORD#<order> -> node_id  (con paginación).
    order_to_node_id: dict[int, str] = {}
    kwargs = {"KeyConditionExpression": Key("PK").eq(f"FLOW#{_COURSE_ID}")}
    while True:
        resp = table.query(**kwargs)
        for it in resp["Items"]:
            order = int(it["SK"].split("#", 1)[1])
            order_to_node_id[order] = it["node_id"]
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # 2) Definiciones de los nodos referenciados: BatchGetItem en lotes de 100
    #    (límite de DynamoDB), reintentando las claves no procesadas.
    table_name = os.environ["CATALOG_TABLE"]
    node_ids = list(set(order_to_node_id.values()))
    nodes_by_id: dict[str, CourseNode] = {}
    for i in range(0, len(node_ids), 100):
        keys = [{"PK": f"NODE#{nid}", "SK": "META"} for nid in node_ids[i : i + 100]]
        request = {table_name: {"Keys": keys}}
        while request:
            resp = ddb.batch_get_item(RequestItems=request)
            for it in resp["Responses"].get(table_name, []):
                node = CourseNode.model_validate(it)  # ignora PK/SK extra
                nodes_by_id[node.node_id] = node
            request = resp.get("UnprocessedKeys") or None

    _order_to_node_id = order_to_node_id
    _nodes_by_id = nodes_by_id


def get_node_at(order: int) -> CourseNode | None:
    """Nodo en la posición `order`, o `None` si es fin de curso (posición inexistente)."""
    _load()
    assert _order_to_node_id is not None and _nodes_by_id is not None
    node_id = _order_to_node_id.get(order)
    if node_id is None:
        return None
    return _nodes_by_id.get(node_id)


def get_node(node_id: str) -> CourseNode | None:
    """Definición de un nodo por su id, o `None` si no existe."""
    _load()
    assert _nodes_by_id is not None
    return _nodes_by_id.get(node_id)


def max_order() -> int:
    """Última posición de la secuencia. 0 si el catálogo está vacío.

    Sirve para distinguir «fin de curso» de «hueco en la secuencia»: sin esto, un
    agujero en la numeración (p. ej. al retirar un nodo sin renumerar) haría que
    `get_node_at` devolviera `None` y el curso terminara en silencio a mitad.
    """
    _load()
    assert _order_to_node_id is not None
    return max(_order_to_node_id) if _order_to_node_id else 0


def reset_cache() -> None:
    """Vacía la caché. Solo para tests; en producción la caché es inmutable por contenedor."""
    global _nodes_by_id, _order_to_node_id
    _nodes_by_id = None
    _order_to_node_id = None
