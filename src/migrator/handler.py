"""Lambda MIGRADORA: aplica las migraciones SQL pendientes.

No tiene `Events:` en la plantilla: se invoca a mano con `make migrate`. Es
deliberado. Si esto fuese un Custom Resource de CloudFormation, una migración
fallida provocaría el rollback del stack ENTERO, incluido el código de las otras
Lambdas que estaba perfectamente bien. Separando el deploy de la aplicación del
esquema, un fallo aquí sale como error de Lambda con sus logs y ya está.

De propina es un smoke test de conectividad e IAM: si el migrador corre, la app
también puede hablar con la base de datos.
"""

from typing import TYPE_CHECKING, Any

from migrator import runner
from shared.observability import logger, tracer

if TYPE_CHECKING:
    from aws_lambda_typing.context import Context


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict[str, Any], context: "Context") -> dict[str, Any]:
    result = runner.run()
    return {
        "ok": True,
        "applied": result["applied"],
        "skipped": result["skipped"],
    }
