"""Checkpointer: la memoria del grafo, PERSISTIDA fuera del proceso.

Por qué no MemorySaver:
  Lambda reutiliza el contenedor entre invocaciones sólo A VECES. Si el siguiente
  mensaje cae en un contenedor nuevo, la memoria en RAM está vacía y el tutor/bot
  "recuerda a ratos" — el peor tipo de bug (no falla, se comporta raro).

El estado vive en DynamoDB, con `thread_id` (= número de teléfono) como partición.
Cualquier instancia puede así retomar cualquier conversación: eso es lo que
habilita el escalado horizontal.
"""

import os

from langgraph_checkpoint_aws import DynamoDBSaver

# 7 días
TTL_SEGUNDOS = 86400 * 7


def get_checkpointer() -> DynamoDBSaver:
    """Devuelve el checkpointer persistente para compilar el grafo."""
    return DynamoDBSaver(
        table_name=os.environ["CHECKPOINT_TABLE"],
        # Lambda inyecta AWS_REGION automáticamente en el runtime.
        region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        ttl_seconds=TTL_SEGUNDOS,
        enable_checkpoint_compression=True,
    )
