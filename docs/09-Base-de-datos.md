# 09 · Base de datos

PostgreSQL (Aurora Serverless v2) con el contenido del curso y el progreso de los alumnos.

## Por qué Aurora + Data API

Las Lambdas **no están en la VPC** y acceden a la base de datos por HTTPS con el
[RDS Data API](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.html) (`boto3`, cliente `rds-data`).

La alternativa —una conexión TCP normal con `psycopg`— obligaría a meter las Lambdas dentro de la VPC, y como el worker necesita salir a internet (Bedrock, Kapso, LangSmith, endpoint de Spoky), eso arrastraría un **NAT Gateway (~35 USD/mes)** solo para no perder esa salida. Con el Data API la base de datos vive en subnets privadas sin puertos abiertos, no hay NAT, y `psycopg` no engorda el bundle.

Consecuencias de este diseño, todas visibles en el código:

- **Una sentencia por llamada.** El Data API rechaza varias sentencias juntas, así que el runner trocea cada `.sql` (`migrator/runner.py::split_sql`).
- **El cluster se pausa.** Con `MinCapacity: 0` Aurora escala a cero y deja de facturar cómputo; la primera consulta tras la pausa tarda decenas de segundos. `shared/db.py` lo reintenta con backoff hasta 90 s.
- **La red no da acceso.** El security group no tiene reglas de entrada a propósito: quien no pueda usar el Data API no entra, y punto.

## Esquema

| Tabla | Clave | Para qué |
|---|---|---|
| `nodes` | `id` (`R0-01`, `E1-01-01`, …) | Los 70 nodos de contenido del curso. |
| `flow_sequence` | `id` | Las 70 posiciones del recorrido. `node_id` → FK a `nodes`. |
| `users` | `thread_id` | El alumno. `thread_id` es el número de teléfono: la misma clave que el worker usa como `thread_id` del grafo. |
| `progress` | `(thread_id, node_id)` | Avance del alumno por cada nodo. |
| `processed_events` | `idempotency_key` | Idempotencia de eventos entrantes. |

Detalles que no se ven en la lista:

- **`step_order`, no `order`**: la columna del CSV se llama `order`, que es palabra reservada en SQL.
- **`stage`/`mission` son NULLables**: 42 de los 70 nodos traen etapa desde `assets.xlsx`; los 28 sub-nodos la derivan del prefijo del id. Los nodos `R0-*` (registro y consentimiento) **no tienen etapa**: quedan en `NULL`, que no es lo mismo que la etapa `0`.
- **La FK de `flow_sequence`** es lo que garantiza, por construcción, que no haya referencias a nodos inexistentes.
- **`users` guarda PII de un adulto responsable** (`guardian_*`), que es lo que pide el nodo `R0-01`. Su borrado debe ser una operación explícita, nunca automática.
- **`CHECK` en vez de `ENUM`**: `ALTER TYPE` no es cómodo de hacer idempotente y el vocabulario de `output` es inestable (`No Apply`, `[message]`, `message + gif`).

### Limpieza de `processed_events`

Postgres **no expira filas solo**, a diferencia del atributo `ttl` de DynamoDB. La columna `expires_at` (con índice) existe para poder barrer:

```sql
DELETE FROM processed_events WHERE expires_at < now();
```

A este volumen la tabla es despreciable durante años, así que **no** hay ninguna Lambda programada para esto. Si algún día crece, la vía de escalado es un `AWS::Events::Rule` + una Lambda mínima con ese `DELETE`, o particionar por día.

> Hoy la idempotencia real sigue viviendo en DynamoDB (`StateTable`, en `receiver/handler.py`). `processed_events` es el estado objetivo para cuando se migre; por eso `ReceiverFn` todavía no tiene permisos de Data API.

## Flujo de trabajo

### Cambiar los datos del curso

Los ficheros fuente (`tb_nodes.csv`, `tb_flow_sequence.csv`, `assets.xlsx`) **no están versionados**: viven fuera del repo. Lo que se versiona es el SQL generado.

```sh
make seed-sql                    # regenera src/migrations/003 y 004
git diff src/migrations/         # revisar SIEMPRE, sobre todo el escapado de apóstrofes
```

`DATA_DIR` apunta al directorio padre por defecto; se puede cambiar: `make seed-sql DATA_DIR=/ruta/a/los/datos`.

El generador excluye los assets con `status = 'Descartado'` y aborta si `flow_sequence` referencia un nodo que no existe.

### Desplegar y poblar

```sh
make deploy      # crea/actualiza el stack (la PRIMERA vez tarda 10-15 min por el cluster)
make migrate     # aplica las migraciones pendientes
make db-counts   # comprobaciones de aceptación
```

`make db-counts` debe imprimir **70 / 70 / 42 / 2**: nodos, posiciones del flujo, nodos enriquecidos y nodos sin etapa (los dos `R0-*`).

> La primera invocación del día de `make migrate` puede tardar ~1 minuto: el cluster estaba pausado y está reanudando. No es un fallo.

### Añadir una migración

Ficheros en `src/migrations/`, numerados, en orden lexicográfico. Van **dentro de `src/`** porque el `CodeUri` de SAM es `../src`: un directorio en la raíz del repo no llegaría al artefacto desplegado y el migrador no encontraría nada que aplicar.

**Nunca edites una migración ya aplicada.** El runner guarda un checksum de cada una en `schema_migrations` y aborta si el contenido cambió:

```
La migración '001_schema.sql' ya se aplicó pero su contenido ha cambiado.
No edites una migración aplicada: crea una nueva.
```

Es deliberado: ignorarlo en silencio es justo como los entornos empiezan a divergir. Si necesitas cambiar algo ya aplicado, añade una migración nueva.

Los seeds (`003`, `004`) son la excepción parcial: se regeneran con `make seed-sql` y usan `ON CONFLICT ... DO UPDATE`, así que **re-ejecutarlos no duplica nada**. Pero si su contenido cambia después de haberse aplicado, el checksum salta igual; en ese caso hay que renumerar el fichero regenerado como una migración nueva (`005_seed_nodes.sql`).

### Consultar la base de datos a mano

Sin cliente de Postgres, con el Data API:

```sh
CLUSTER=$(aws cloudformation describe-stacks --stack-name kapso-whatsapp-bot \
  --query 'Stacks[0].Outputs[?OutputKey==`DbClusterArn`].OutputValue' --output text)
SECRET=$(aws cloudformation describe-stacks --stack-name kapso-whatsapp-bot \
  --query 'Stacks[0].Outputs[?OutputKey==`DbSecretArn`].OutputValue' --output text)

aws rds-data execute-statement --resource-arn "$CLUSTER" --secret-arn "$SECRET" \
  --database waku --sql "SELECT id, stage, objective FROM nodes ORDER BY id LIMIT 5"
```

## Credenciales

No hay ninguna contraseña en el repositorio, ni en CloudFormation, ni en los secrets de GitHub.

El cluster usa `ManageMasterUserPassword: true`: **AWS crea y rota** la contraseña en Secrets Manager. Las Lambdas solo reciben el ARN del secreto (`!GetAtt DBCluster.MasterUserSecret.SecretArn`), que es estable frente a la rotación, y la política IAM acota `secretsmanager:GetSecretValue` a ese ARN concreto.

La política del Data API incluye las **tres acciones de transacción** (`BeginTransaction`, `CommitTransaction`, `RollbackTransaction`) además de `ExecuteStatement`. Son acciones IAM separadas: sin ellas el migrador falla con un `AccessDenied` opaco al abrir la transacción.

## Borrado del stack

`DBCluster` tiene `DeletionPolicy: Snapshot`, así que `sam delete` **no** se lleva por delante los datos de los alumnos: deja un snapshot.

Efecto secundario a tener presente: si más adelante se recrea y se vuelve a borrar el stack, el borrado **falla** si ya existe un snapshot con el mismo nombre. Hay que borrar el snapshot viejo a mano.
