"""Re-encolado de la continuación de una cadena de nodos.

Cuando una invocación alcanza `MAX_NODES_PER_INVOCATION`, en vez de seguir enviando
hasta agotar el `Timeout: 120` del worker, se encola un mensaje de continuación con
`DelaySeconds`. Lambda se lo entrega de vuelta al worker y la cadena sigue desde la
posición ya persistida en `CourseStateTable`.

El mensaje NO es un `WebhookIn`: lleva su propio marcador para que el worker lo
distinga de un mensaje real del alumno. Reencolar el webhook original haría que el
texto del alumno se procesara dos veces.
"""

import json
import os

import boto3

MARCADOR = "course_continuation"


def _sqs():
    # Perezoso, como en catalog.py y repository.py: crear el cliente al importar exige
    # región configurada, y este módulo lo importa el worker (y los tests) siempre.
    return boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "eu-west-1"))


def enqueue_continuation(phone: str, phone_number_id: str, delay_seconds: int = 2) -> None:
    _sqs().send_message(
        QueueUrl=os.environ["QUEUE_URL"],
        MessageBody=json.dumps(
            {"type": MARCADOR, "phone": phone, "phone_number_id": phone_number_id}
        ),
        DelaySeconds=delay_seconds,
    )


def parse_continuation(body: str) -> dict | None:
    """Devuelve los datos de la continuación, o `None` si es un mensaje normal."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("type") == MARCADOR else None
