"""Lambda RECEPTOR del webhook de Kapso.

Responsabilidad (debe ser RÁPIDA: responder 200 en < 10 s):
  1) Validar la firma HMAC-SHA256 sobre el CUERPO CRUDO (cabecera X-Webhook-Signature).
  2) Comprobar idempotencia contra DynamoDB (cabecera X-Idempotency-Key).
  3) Encolar el evento en SQS.
  4) Devolver 200 OK de inmediato. NADA de lógica de negocio aquí.
"""

import base64
import os
import time
from typing import TYPE_CHECKING, Any

import boto3

from shared.observability import logger, tracer
from shared.signature import verify_signature

if TYPE_CHECKING:
    from aws_lambda_typing.context import Context
    from aws_lambda_typing.events import APIGatewayProxyEventV2

dynamo = boto3.client("dynamodb")
sqs = boto3.client("sqs")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: "APIGatewayProxyEventV2", context: "Context") -> dict[str, Any]:

    if event.get("isBase64Encoded"):
        raw = base64.b64decode(event["body"])
    else:
        raw = event["body"].encode("utf-8")
    text = raw.decode("utf-8")
    signature = event.get("headers", {}).get("x-webhook-signature")

    secret = os.environ.get("KAPSO_WEBHOOK_SECRET")
    if not secret:
        logger.error("Falta KAPSO_WEBHOOK_SECRET en el entorno")
        return {"statusCode": 500, "body": "Server misconfigured"}
    if signature is None or not verify_signature(raw, signature, secret):
        logger.warning("Firma inválida o ausente")
        return {"statusCode": 401, "body": "Invalid signature"}

    idem = event.get("headers", {}).get("x-idempotency-key")

    if idem is not None:
        logger.append_keys(idempotency_key=idem)

    if idem is None:
        sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=text)
        logger.info("Evento encolado sin clave de idempotencia")
        return {"statusCode": 200, "body": "OK"}

    try:
        dynamo.put_item(
            TableName=os.environ["TABLE_NAME"],
            Item={"pk": {"S": f"idem#{idem}"}, "ttl": {"N": str(int(time.time()) + 86400)}},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except dynamo.exceptions.ConditionalCheckFailedException:
        logger.info("Evento duplicado, ignorado")
        return {"statusCode": 200, "body": "duplicate"}

    sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=text)
    logger.info("Evento encolado")
    return {"statusCode": 200, "body": "OK"}
