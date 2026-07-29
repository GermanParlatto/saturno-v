"""Lambda WORKER: consume de SQS e invoca el motor de curso.

Devuelve `batchItemFailures` para que Lambda reintente SÓLO los
mensajes que fallaron, no el lote entero (requiere FunctionResponseTypes:
ReportBatchItemFailures en la plantilla). Sin esto, con BatchSize=10 un solo
fallo reenviaría nueve respuestas duplicadas.

El worker ya NO envía la respuesta: `run_course` envía por Kapso a medida que recorre
nodos, porque una invocación puede producir varios mensajes (cadena de `pauses=false`)
o ninguno (el alumno responde a un nodo que solo evalúa). `agents.app.run_graph`
—START→llm→END— deja de invocarse; el código sigue en el repo sin ruta que lo alcance.

Dos clases de mensaje llegan por la cola:
  * webhooks reales del alumno (`WebhookIn`), reenviados por el receiver;
  * continuaciones que el propio motor se auto-encola al alcanzar el tope de nodos
    por invocación (ver `course/continuation.py`).
"""

import hashlib
from typing import TYPE_CHECKING, Any

from langchain_core.tracers.langchain import wait_for_all_tracers

from course.app import run_course
from course.continuation import parse_continuation
from shared.models import WebhookIn
from shared.observability import logger, metrics, tracer

if TYPE_CHECKING:
    from aws_lambda_typing.context import Context
    from aws_lambda_typing.events import SQSEvent


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: "SQSEvent", context: "Context") -> dict[str, Any]:
    fallidos: list[dict[str, str]] = []

    for record in event["Records"]:
        try:
            continuacion = parse_continuation(record["body"])
            if continuacion:
                # No lleva texto del alumno: solo reanuda la cadena donde la dejó la
                # invocación anterior, desde la posición ya persistida en DynamoDB.
                logger.append_keys(conversation_id=continuacion["phone"])
                logger.info("Continuación de cadena de nodos")
                run_course(
                    continuacion["phone"],
                    text="",
                    phone_number_id=continuacion["phone_number_id"],
                )
                continue

            data = WebhookIn.model_validate_json(record["body"])
            numero = data.message.sender
            texto = data.message.text.body
            phone_number_id = data.phone_number_id

            logger.append_keys(conversation_id=numero)
            # No registrar el texto del alumno (PII): puede contener nombre, correo y
            # teléfono del tutor (R0-01). Se emite longitud + hash corto, suficiente para
            # correlacionar duplicados sin exponer el contenido en CloudWatch.
            logger.info(
                "Procesando mensaje",
                extra={
                    "texto_len": len(texto),
                    "texto_hash": hashlib.sha256(texto.encode()).hexdigest()[:12],
                },
            )

            estado = run_course(numero, text=texto, phone_number_id=phone_number_id)

            logger.info(
                "Curso avanzado",
                extra={
                    "mensajes_enviados": estado.get("sent_count", 0),
                    "current_order": estado.get("current_order"),
                    "waiting": estado.get("waiting", False),
                    "course_completed": estado.get("course_completed", False),
                },
            )

        except Exception:
            # Marcamos SÓLO este mensaje como fallido; los demás del lote se borran.
            logger.exception(f"Error procesando mensaje {record['messageId']}")
            fallidos.append({"itemIdentifier": record["messageId"]})

    # LangSmith sube las trazas en un hilo de fondo; en Lambda el contenedor se
    # congela al devolver y se perderían. Forzamos el flush antes de salir.
    wait_for_all_tracers()

    return {"batchItemFailures": fallidos}
