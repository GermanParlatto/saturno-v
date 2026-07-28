# 08 · Configuración

Variables de entorno de las dos Lambdas, de dónde salen y qué pasa si falta cada una.

## Receiver

| Variable | Obligatoria | Default | Origen | Si falta |
|---|---|---|---|---|
| `KAPSO_WEBHOOK_SECRET` | sí | — | Parámetro SAM `KapsoWebhookSecret` ← secret de GitHub | El deploy rechaza (`MinLength: 1`); en runtime, todos los webhooks se rechazarían por firma inválida. |
| `QUEUE_URL` | sí | — | `!Ref IncomingQueue` (interno, no es secreto) | `KeyError` al importar el handler. |
| `TABLE_NAME` | sí | — | `!Ref StateTable` (interno) | `KeyError` al importar el handler. |

## Worker

| Variable | Obligatoria | Default | Origen | Si falta |
|---|---|---|---|---|
| `KAPSO_API_KEY` | sí | — | Parámetro SAM `KapsoApiKey` ← secret de GitHub | `RuntimeError` al enviar por Kapso (guardado en `kapso_client.py`). |
| `MODEL_ID` | sí | `eu.amazon.nova-2-lite-v1:0` | Parámetro SAM `ModelId` | `KeyError` al importar `agents/nodes/llm.py`. |
| `CHECKPOINT_TABLE` | sí | — | `!Ref CheckpointTable` (interno) | `KeyError` al construir el checkpointer. |
| `LANGSMITH_TRACING` | no | `"true"` (fijo en el template) | — | Sin trazas de LangSmith. |
| `LANGSMITH_API_KEY` | sí | — | Parámetro SAM `LangsmithApiKey` ← secret de GitHub | El deploy rechaza (`MinLength: 1`). |
| `LANGSMITH_PROJECT` | no | `spoky-bot` (fijo) | — | — |
| `LANGSMITH_ENDPOINT` | no | `https://eu.api.smith.langchain.com` (fijo) | — | — |
| `SPOKY_ENDPOINT_URL` | sí | — | Parámetro SAM `SpokyEndpointUrl` ← secret de GitHub | El deploy rechaza (`MinLength: 1`); en runtime, `SpokyConfigError` y el finalizador cae al borrador del tutor (nunca rompe el pipeline). |
| `SPOKY_API_TOKEN` | sí | — | Parámetro SAM `SpokyApiToken` (`NoEcho`) ← secret de GitHub | Igual que arriba: `SpokyConfigError` + fallback. |
| `SPOKY_MODEL_NAME` | no | `GParlatto/spoky-qwen-merged-v2` | — | Se usa el default. |
| `SPOKY_TIMEOUT_SECONDS` | no | `25` | Fijo en el template (`WorkerFn`) | Se usa el default. |
| `DB_CLUSTER_ARN` | sí | — | `!GetAtt DBCluster.DBClusterArn` (interno) | `KeyError` al primer acceso a la BD. |
| `DB_SECRET_ARN` | sí | — | `!GetAtt DBCluster.MasterUserSecret.SecretArn` (interno) | `KeyError` al primer acceso a la BD. |
| `DB_NAME` | sí | `waku` | Parámetro SAM `DbName` (no es secreto) | `KeyError` al primer acceso a la BD. |

## Migrador (`MigrationFn`)

Se invoca a mano (`make migrate`), no tiene `Events:`. Ver [09 · Base de datos](09-Base-de-datos.md).

| Variable | Obligatoria | Default | Origen | Si falta |
|---|---|---|---|---|
| `DB_CLUSTER_ARN` | sí | — | `!GetAtt DBCluster.DBClusterArn` (interno) | `KeyError` al aplicar migraciones. |
| `DB_SECRET_ARN` | sí | — | `!GetAtt DBCluster.MasterUserSecret.SecretArn` (interno) | `KeyError` al aplicar migraciones. |
| `DB_NAME` | sí | `waku` | Parámetro SAM `DbName` | `KeyError` al aplicar migraciones. |

## Globales (ambas Lambdas)

| Variable | Valor | Motivo |
|---|---|---|
| `POWERTOOLS_LOG_LEVEL` | `INFO` | Sin esto Powertools filtra a WARNING y los `logger.info` no aparecen. |
| `POWERTOOLS_SERVICE_NAME` | `kapso-bot` | Nombre homogéneo en logs y trazas X-Ray. |
| `POWERTOOLS_METRICS_NAMESPACE` | `kapso-bot` | Namespace de CloudWatch para las métricas EMF (`FinalizerOk`, `FinalizerFallback`, etc.). |

`AWS_REGION` la inyecta Lambda automáticamente; el código usa `os.environ.get("AWS_REGION", "eu-west-1")` como fallback para ejecución local.

## Métricas del finalizador

Emitidas con `aws_lambda_powertools.Metrics` bajo el namespace `kapso-bot`:

| Métrica | Cuándo se emite |
|---|---|
| `FinalizerOk` | La reescritura de Spoky se aplicó con éxito. |
| `FinalizerOmitido` | No había borrador válido; no se llamó al endpoint. |
| `FinalizerFallback` | Cualquier fallo del endpoint (config, red, timeout, HTTP, estructura); se envió el borrador del tutor. |
| `FinalizerCodigoAlterado` | La reescritura perdió algún fragmento de código del borrador; se descartó y se envió el borrador. |

Si `FinalizerFallback` o `FinalizerCodigoAlterado` suben mucho, revisar primero si el endpoint está frío (ver abajo) antes de tocar el prompt.

## Presupuesto de timeout y arranque en frío

`WorkerFn` tiene `Timeout: 120`, por debajo del `VisibilityTimeout: 180` de la cola SQS (regla: el segundo debe ser mayor que el primero, o un mensaje reaparecería mientras aún se procesa).

| Etapa | Caliente | Endpoint de Spoky en frío |
|---|---|---|
| Bedrock Nova (≤500 tok) | 2-6 s | 2-6 s |
| Spoky (≤200 tok) | 1-3 s | **30-60 s** (arranque en frío del endpoint HF) |
| Envío por Kapso | <1 s | <1 s |
| **Total** | ~5-10 s | ~40-70 s |

Un mensaje aislado en frío cabe en el `Timeout: 120`. El riesgo real es el **lote**: el handler de `worker/handler.py` procesa los mensajes de un lote SQS en serie, así que varios mensajes contra un endpoint frío agotarían el timeout del Lambda y devolverían el lote entero a la cola. Por eso el evento SQS de `WorkerFn` usa `BatchSize: 3` (no 10): acota el peor caso secuencial para que quepa con margen. `MaximumConcurrency: 5` compensa el rendimiento con más invocaciones paralelas y más pequeñas.

El endpoint de HF puede seguir escalando a cero. Si las métricas de fallback indican que el arranque en frío es frecuente, la siguiente palanca (fuera de este repo) es fijar réplicas mínimas = 1 en la consola de Hugging Face.

## Checklist al añadir un nuevo secreto

Un secreto nuevo requiere editar tres sitios coordinados, o el deploy falla o despliega con el valor vacío:

1. `infra/template.yaml` → bloque `Parameters` (con `NoEcho: true, MinLength: 1` si es secreto).
2. `infra/template.yaml` → `Environment.Variables` de la función que lo consume.
3. `.github/workflows/deploy.yml` → el bucle "Verificar que los secrets existen" (nombre + su `env:`) y el paso `sam deploy` (`--parameter-overrides` + su `env:`).

Y no olvidar dar de alta el secret en el entorno `production` de GitHub (Settings → Environments → production → Secrets).

### Cuándo NO aplica este checklist

Las credenciales de la base de datos **no** siguen los pasos de arriba, y añadirlas al bucle de `deploy.yml` haría fallar el deploy por un secret de GitHub que no existe.

`DB_CLUSTER_ARN`, `DB_SECRET_ARN` y `DB_NAME` no son secretos de GitHub: los dos primeros salen de un `!GetAtt` sobre el cluster dentro del propio template, y `DB_NAME` es un parámetro sin `NoEcho`. La contraseña de la base de datos **nunca existe como secret**: la crea y la rota AWS (`ManageMasterUserPassword: true`), y las Lambdas solo referencian el ARN del secreto gestionado, que es estable frente a la rotación.

Regla general: si el valor sale de un `!Ref`/`!GetAtt` a otro recurso del stack, es interno y solo requiere el paso 2.
