# 09 · Capa de datos

Todo el estado vive en DynamoDB, en tres tablas con responsabilidades separadas. No hay
base de datos relacional: una primera iteración usó Aurora Serverless v2 con la Data API,
pero el motor de curso se construyó sobre DynamoDB y el cluster quedó sin lectores.

Consecuencia de diseño que merece la pena señalar: al no haber Aurora, **las Lambdas no
necesitan VPC**. Sin VPC no hay subnets, ni security groups, ni NAT Gateway (unos 35
USD/mes solo por existir). El coste de red del proyecto es cero.

## Tablas

Las tres son `PAY_PER_REQUEST` y se definen en [`infra/template.yaml`](../infra/template.yaml).

### `StateTable` — idempotencia del webhook

| | |
|---|---|
| Clave | `pk` (S) |
| TTL | `ttl`, 24 h |
| Escribe | `ReceiverFn` |

Un ítem por clave de idempotencia (`idem#<X-Idempotency-Key>`), escrito con
`attribute_not_exists` antes de encolar. Kapso entrega at-least-once: sin esto, un
reintento del webhook reproduciría la lección. El TTL es correcto aquí porque una clave
repetida 24 h después ya no es un reintento.

### `CourseCatalogTable` — definición del curso

| | |
|---|---|
| Clave | `PK` (S) + `SK` (S) |
| TTL | ninguno (el contenido no caduca) |
| SSE | activado |
| Acceso del worker | **solo lectura** |

| PK | SK | Contenido |
|---|---|---|
| `NODE#<id>` | `META` | Un nodo: tipo, descripción, `pauses`, `eval_type`, `media_kind`, `file_url`, `question` |
| `FLOW#<curso>` | `ORD#<n>` | La posición `n` de la secuencia → `node_id` |
| `CATALOG#<curso>` | `VERSION` | Ítem de control del seeder (ver abajo) |

Es contenido estático (~70 nodos), así que [`course/catalog.py`](../src/course/catalog.py)
lo carga entero en RAM la primera vez y lo cachea por contenedor Lambda: una `Query` sobre
el `FLOW` más un `BatchGetItem` paginado de los nodos, y a partir de ahí cero lecturas.

### `CourseStateTable` — progreso del alumno

| | |
|---|---|
| Clave | `PK` = `USER#<teléfono>`, `SK` = `STATE` |
| TTL | **ninguno, a propósito** |
| SSE | activado |
| Acceso del worker | lectura + escritura condicional |

Dos decisiones deliberadas:

- **Sin TTL.** Un curso dura meses y un alumno puede desaparecer semanas. Cualquier TTL
  heredado de una caché de conversación borraría el progreso a mitad del curso.
- **SSE activado.** La tabla guarda el nombre del alumno (un menor) y el nombre, correo y
  teléfono del adulto responsable. El worker además nunca loguea el texto de entrada:
  registra su longitud y un hash de 12 caracteres.

## Concurrencia: escrituras condicionales en vez de bloqueos

SQS entrega at-least-once, así que dos invocaciones pueden ver al mismo alumno en la misma
posición. [`course/repository.py`](../src/course/repository.py) lo resuelve sin bloqueos:

- `create_user` escribe con `ConditionExpression="attribute_not_exists(PK)"`. Si dos
  mensajes del alumno llegan a la vez, solo uno da de alta.
- `advance_position` actualiza con `ConditionExpression="current_order = :expected"`. Si
  otra invocación ya movió al alumno, esta pierde la carrera.

En ambos casos el perdedor recibe `PositionConflict` y **para**, en vez de avanzar dos
posiciones. Es lo que convierte un duplicado de SQS en un no-op en lugar de una lección
saltada.

`version` se incrementa en cada avance, para auditoría.

## Sembrado del catálogo, gobernado por versión

El catálogo se genera desde [`data/`](../data/) con
[`tools/seed-course.py`](../tools/seed-course.py). El protocolo:

1. El script lleva una constante `CATALOG_VERSION`.
2. En la tabla hay un ítem de control `CATALOG#<curso> / VERSION`.
3. Si coinciden, el seeder **no escribe nada** y sale con 0.
4. Si difieren, re-siembra el catálogo entero y actualiza el ítem de control.

Al cambiar una derivación o un texto del curso hay que subir `CATALOG_VERSION` en el mismo
commit; si no, el despliegue no propaga el cambio.

[`seed.yml`](../.github/workflows/seed.yml) lo ejecuta automáticamente tras un deploy
correcto. Una versión anterior del workflow tenía una guarda del tipo «si la tabla ya
tiene ítems, no la toques», que congelaba el catálogo para siempre tras la primera siembra:
de ahí que hoy la decisión de escribir sea del seeder y no del YAML.

### Assets

El CSV guarda **rutas relativas** (`E1-01.png`), no URLs absolutas. El seeder las resuelve
contra `ASSET_BASE_URL`, que llega como secreto: qué bucket sirve los assets es
configuración de despliegue y no queda grabado en el repo. Sin esa variable el nodo se
siembra sin media, en vez de con una URL rota.
