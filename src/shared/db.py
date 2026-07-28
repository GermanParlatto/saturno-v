"""Acceso a Aurora PostgreSQL vía RDS Data API (HTTPS, sin VPC ni psycopg).

Por qué Data API y no una conexión TCP normal: las Lambdas de este proyecto NO
están en la VPC. Salen a internet a Bedrock, Kapso, LangSmith y el endpoint de
Spoky; meterlas en la VPC obligaría a un NAT Gateway solo para no perder esa
salida. El Data API habla HTTPS contra un endpoint público de AWS, así que la
base de datos vive en subnets privadas sin que nadie abra un puerto.

Este módulo lo importan tanto la app como el migrador: es el único sitio donde
se traduce entre valores de Python y el formato de parámetros del Data API, que
es lo bastante puntilloso como para no querer repetirlo.
"""

import json
import os
import time
from typing import Any

import boto3
from botocore.config import Config

from shared.observability import logger

_client_cache = None


def _client():
    """Cliente perezoso y cacheado entre invocaciones.

    No se crea al importar a propósito: `boto3.client()` resuelve credenciales
    en ese momento, así que un cliente a nivel de módulo haría fallar el import
    en el CI (que no tiene credenciales) y en cualquier test que importe esto.
    Cacheado, sigue reutilizándose entre invocaciones de la misma Lambda.
    """
    global _client_cache
    if _client_cache is None:
        # Los reintentos por defecto de botocore son escasos para un cluster que
        # puede estar reanudándose.
        _client_cache = boto3.client(
            "rds-data", config=Config(retries={"max_attempts": 3, "mode": "standard"})
        )
    return _client_cache


# Aurora Serverless v2 con MinCapacity 0 se PAUSA. La primera llamada tras la
# pausa falla mientras el cluster levanta: no es un error real, es un arranque en
# frío que tarda decenas de segundos. Sin este reintento, el primer `make
# migrate` del día falla de forma incomprensible.
_RESUME_ERRORS = ("DatabaseResumingException", "DatabaseErrorException")
_RESUME_MAX_WAIT_SECONDS = 90


def _cfg() -> dict[str, str]:
    """ARNs y nombre de BD. Se leen en cada llamada, no al importar, para que los
    tests puedan usar monkeypatch sobre el entorno."""
    return {
        "resourceArn": os.environ["DB_CLUSTER_ARN"],
        "secretArn": os.environ["DB_SECRET_ARN"],
        "database": os.environ["DB_NAME"],
    }


def to_param(name: str, value: Any) -> dict[str, Any]:
    """Convierte un valor de Python al formato de parámetro del Data API.

    El orden de los `isinstance` importa: bool es subclase de int en Python, así
    que comprobarlo después de int convertiría True en 1.
    """
    if value is None:
        field: dict[str, Any] = {"isNull": True}
    elif isinstance(value, bool):
        field = {"booleanValue": value}
    elif isinstance(value, int):
        field = {"longValue": value}
    elif isinstance(value, float):
        field = {"doubleValue": value}
    elif isinstance(value, dict | list):
        # JSONB viaja como texto; el CAST se hace en el SQL (::jsonb).
        field = {"stringValue": json.dumps(value, ensure_ascii=False)}
    else:
        field = {"stringValue": str(value)}
    return {"name": name, "value": field}


def _unwrap(field: dict[str, Any]) -> Any:
    """Extrae el valor de una celda de la respuesta del Data API."""
    if field.get("isNull"):
        return None
    for key in ("stringValue", "longValue", "booleanValue", "doubleValue", "blobValue"):
        if key in field:
            return field[key]
    return None


def rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte una respuesta del Data API en una lista de dicts.

    Requiere haber llamado con includeResultMetadata=True (lo hace `execute`),
    porque si no la respuesta trae valores sin nombres de columna.
    """
    columns = [c["name"] for c in response.get("columnMetadata", [])]
    return [
        dict(zip(columns, (_unwrap(cell) for cell in record), strict=True))
        for record in response.get("records", [])
    ]


def _with_resume_retry(call, *, description: str):
    """Ejecuta `call`, reintentando mientras el cluster esté reanudándose."""
    deadline = time.monotonic() + _RESUME_MAX_WAIT_SECONDS
    delay = 2.0
    while True:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - se re-lanza salvo el caso de reanudación
            name = type(exc).__name__
            resuming = name in _RESUME_ERRORS or "resuming" in str(exc).lower()
            if not resuming or time.monotonic() >= deadline:
                raise
            logger.info(
                "Cluster reanudándose, reintentando",
                extra={"operacion": description, "espera_s": delay},
            )
            time.sleep(delay)
            delay = min(delay * 2, 15.0)


def execute(
    sql: str,
    parameters: dict[str, Any] | None = None,
    *,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    """Ejecuta UNA sentencia. El Data API rechaza varias en la misma llamada."""
    kwargs: dict[str, Any] = {
        **_cfg(),
        "sql": sql,
        "includeResultMetadata": True,
    }
    if parameters:
        kwargs["parameters"] = [to_param(k, v) for k, v in parameters.items()]
    if transaction_id:
        kwargs["transactionId"] = transaction_id
        # Dentro de una transacción el resourceArn manda, pero el database no se
        # admite junto a transactionId.
        kwargs.pop("database", None)
    return _with_resume_retry(lambda: _client().execute_statement(**kwargs), description="execute")


def begin_transaction() -> str:
    response = _with_resume_retry(
        lambda: _client().begin_transaction(**_cfg()), description="begin_transaction"
    )
    return response["transactionId"]


def commit_transaction(transaction_id: str) -> None:
    cfg = _cfg()
    _client().commit_transaction(
        resourceArn=cfg["resourceArn"], secretArn=cfg["secretArn"], transactionId=transaction_id
    )


def rollback_transaction(transaction_id: str) -> None:
    cfg = _cfg()
    _client().rollback_transaction(
        resourceArn=cfg["resourceArn"], secretArn=cfg["secretArn"], transactionId=transaction_id
    )
