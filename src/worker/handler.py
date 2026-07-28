"""Lambda WORKER: consume de SQS, invoca el grafo y responde por Kapso.
Una línea. El resto del handler no se entera de que ahora hay un grafo detrás.

devuelve `batchItemFailures` para que Lambda reintente SÓLO los
mensajes que fallaron, no el lote entero (requiere FunctionResponseTypes:
ReportBatchItemFailures en la plantilla). Sin esto, con BatchSize=10 un solo
fallo reenviaría nueve respuestas duplicadas.
"""

from typing import TYPE_CHECKING, Any

from langchain_core.tracers.langchain import wait_for_all_tracers

from agents.app import run_graph
from shared.kapso_client import send_text
from shared.models import WebhookIn
from shared.observability import logger, metrics, tracer
from shared.whatsapp_format import format_for_whatsapp

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
            data = WebhookIn.model_validate_json(record["body"])
            numero = data.message.sender
            texto = data.message.text.body
            phone_number_id = data.phone_number_id

            logger.append_keys(conversation_id=numero)
            logger.info("Procesando mensaje", extra={"texto": texto})

            # thread_id = número de teléfono: la clave natural de la conversación.
            reply = format_for_whatsapp(run_graph(texto, thread_id=numero))

            if not reply.strip():
                # Respuesta vacía (p.ej. el modelo devolvió content=""): no hay nada
                # útil que enviar. Se trata como fallo del mensaje en vez de mandar
                # un WhatsApp vacío al usuario.
                raise ValueError("El grafo devolvió una respuesta vacía")

            send_text(phone_number_id, to=numero, body=reply)

            logger.info("Respuesta enviada")

        except Exception:
            # Marcamos SÓLO este mensaje como fallido; los demás del lote se borran.
            logger.exception(f"Error procesando mensaje {record['messageId']}")
            fallidos.append({"itemIdentifier": record["messageId"]})

    # LangSmith sube las trazas en un hilo de fondo; en Lambda el contenedor se
    # congela al devolver y se perderían. Forzamos el flush antes de salir.
    wait_for_all_tracers()

    return {"batchItemFailures": fallidos}
