"""Estado del alumno en `CourseStateTable` (un ítem por alumno).

`CourseStateTable` es la ÚNICA fuente de verdad de la posición del alumno (por eso el
grafo nuevo no usa checkpointer de LangGraph: evita dos stores que puedan divergir).

El avance de posición usa bloqueo optimista (misma técnica de idempotencia condicional
que `receiver/handler.py`): así una reentrega de SQS que llega tarde no vuelve a avanzar
un nodo ya superado. Se prefiere duplicar un mensaje a saltarse un nodo del curso.
"""

import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from .models import UserState


class PositionConflict(Exception):
    """El `current_order` esperado no coincide: otra invocación ya avanzó. El llamador
    debe abortar sin reenviar (la reentrega llegó tarde)."""


def _table():
    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return ddb.Table(os.environ["COURSE_STATE_TABLE"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(phone: str) -> dict[str, str]:
    return {"PK": f"USER#{phone}", "SK": "STATE"}


def get_user_state(phone: str) -> UserState | None:
    resp = _table().get_item(Key=_key(phone))
    item = resp.get("Item")
    return UserState.model_validate(item) if item else None


def create_user(phone: str, **perfil) -> UserState:
    """Alta de un alumno en `current_order = 1`. Falla si ya existe (no lo pisa)."""
    now = _now()
    state = UserState(
        phone=phone,
        current_order=1,
        version=1,
        waiting=False,
        attempts=0,
        created_at=now,
        updated_at=now,
        last_interaction_at=now,
        **perfil,
    )
    item = {**_key(phone), **state.model_dump(exclude_none=True)}
    try:
        _table().put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise PositionConflict(f"El usuario {phone} ya existe") from e
        raise
    return state


def advance_position(phone: str, expected_order: int, next_order: int, last_node_id: str) -> None:
    """Avanza a `next_order` SOLO si el alumno sigue en `expected_order`.

    Condicionar en `current_order` impide la carrera de doble avance: si dos workers ven
    el mismo `order`, solo uno gana; el otro recibe `PositionConflict`. `version` se
    incrementa para auditoría y uso futuro.
    """
    try:
        _table().update_item(
            Key=_key(phone),
            UpdateExpression=(
                "SET current_order = :next, last_node_id = :lnid, "
                "waiting = :false, updated_at = :now, last_interaction_at = :now "
                "ADD version :one"
            ),
            ConditionExpression="current_order = :expected",
            ExpressionAttributeValues={
                ":next": next_order,
                ":lnid": last_node_id,
                ":false": False,
                ":now": _now(),
                ":one": 1,
                ":expected": expected_order,
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise PositionConflict(
                f"{phone}: se esperaba order={expected_order}, otra invocación ya avanzó"
            ) from e
        raise


def set_waiting(phone: str, waiting: bool) -> None:
    """Marca si el alumno está en pausa esperando respuesta (`pauses=true`)."""
    _table().update_item(
        Key=_key(phone),
        UpdateExpression="SET waiting = :w, updated_at = :now, last_interaction_at = :now",
        ExpressionAttributeValues={":w": waiting, ":now": _now()},
    )


def increment_attempts(phone: str) -> int:
    """Suma 1 al contador de intentos del nodo actual y devuelve el nuevo valor."""
    resp = _table().update_item(
        Key=_key(phone),
        UpdateExpression="SET updated_at = :now, last_interaction_at = :now ADD attempts :one",
        ExpressionAttributeValues={":one": 1, ":now": _now()},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["attempts"])


def reset_attempts(phone: str) -> None:
    """Pone `attempts` a 0 (al pasar a un nodo nuevo)."""
    _table().update_item(
        Key=_key(phone),
        UpdateExpression="SET attempts = :zero, updated_at = :now",
        ExpressionAttributeValues={":zero": 0, ":now": _now()},
    )


def update_profile(phone: str, **campos) -> None:
    """Guarda los datos de perfil extraídos de la respuesta a `R0-01`.

    Se escriben solo los campos con valor: el alta puede llegar incompleta y una
    segunda respuesta completa lo que faltaba, sin pisar lo ya guardado con `None`.

    Estos son datos de contacto de un adulto responsable de un menor. La tabla tiene
    SSE activado y el worker no loguea el texto de entrada (ver F0).
    """
    presentes = {k: v for k, v in campos.items() if v not in (None, "")}
    if not presentes:
        return
    sets = ", ".join(f"{k} = :{k}" for k in presentes)
    valores = {f":{k}": v for k, v in presentes.items()}
    valores[":now"] = _now()
    _table().update_item(
        Key=_key(phone),
        UpdateExpression=f"SET {sets}, updated_at = :now, last_interaction_at = :now",
        ExpressionAttributeValues=valores,
    )


def mark_for_review(phone: str, node_id: str) -> None:
    """Anota un nodo cerrado sin superar, para repasarlo más adelante.

    `list_append` sobre una lista que puede no existir: `if_not_exists` la inicializa
    vacía en el mismo UpdateExpression, así no hace falta leer antes de escribir.
    """
    _table().update_item(
        Key=_key(phone),
        UpdateExpression=(
            "SET review_nodes = list_append(if_not_exists(review_nodes, :vacia), :nodo), "
            "updated_at = :now"
        ),
        ExpressionAttributeValues={":vacia": [], ":nodo": [node_id], ":now": _now()},
    )
