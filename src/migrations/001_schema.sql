-- Esquema base de Waku Code: contenido del curso (nodes, flow_sequence) y
-- estado del alumno (users, progress, processed_events).
--
-- CHECK en vez de ENUM de Postgres: ALTER TYPE no es comodo de hacer idempotente
-- y el vocabulario de `output` es inestable ('No Apply', '[message]',
-- 'message + gif'). Un CHECK se borra y se recrea en una migracion normal.

-- ------------------------------------------------------------------- nodes
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    function    TEXT NOT NULL,
    pauses      BOOLEAN NOT NULL,
    description TEXT,
    output      TEXT,
    logic       TEXT,
    file_url    TEXT,

    -- Enriquecimiento desde assets.xlsx (42 de 70 nodos) o derivado del prefijo
    -- del id. NULLables A PROPOSITO: las filas R0-* no traen stage/mission en la
    -- hoja (vienen vacias, no como 0), y los 28 sub-nodos no traen objective.
    stage     SMALLINT,
    mission   SMALLINT,
    objective TEXT,
    metadata  JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT nodes_type_chk
        CHECK (type IN ('cheatsheet', 'comic', 'gif', 'image', 'message', 'video')),
    CONSTRAINT nodes_function_chk
        CHECK (function IN ('HUM', 'INT', 'MOT', 'NAR', 'PED')),
    CONSTRAINT nodes_output_chk
        CHECK (output IS NULL OR output IN (
            'No Apply', '[message]', 'cheatsheet', 'comic', 'gif',
            'image', 'message', 'message + gif', 'video')),
    CONSTRAINT nodes_stage_chk   CHECK (stage   IS NULL OR stage   BETWEEN 0 AND 5),
    CONSTRAINT nodes_mission_chk CHECK (mission IS NULL OR mission BETWEEN 0 AND 5)
);

CREATE INDEX IF NOT EXISTS nodes_stage_mission_idx ON nodes (stage, mission);

-- ----------------------------------------------------------- flow_sequence
-- La columna del CSV se llama `order`, que es PALABRA RESERVADA en SQL: aqui es
-- step_order. La FK a nodes es la que garantiza, por construccion, que no haya
-- referencias a nodos inexistentes.
CREATE TABLE IF NOT EXISTS flow_sequence (
    id         INTEGER PRIMARY KEY,
    step_order INTEGER NOT NULL,
    node_id    TEXT NOT NULL
               REFERENCES nodes (id) ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT flow_sequence_order_uniq UNIQUE (step_order),
    CONSTRAINT flow_sequence_node_uniq  UNIQUE (node_id),
    CONSTRAINT flow_sequence_order_pos  CHECK (step_order > 0)
);

-- ------------------------------------------------------------------- users
-- thread_id = numero de telefono: la misma clave que el worker ya usa como
-- thread_id del grafo y el checkpointer de DynamoDB. Es la clave natural.
--
-- OJO: guarda PII de un adulto responsable (lo exige el nodo R0-01, que pide
-- autorizacion). Su borrado debe ser una operacion explicita, NUNCA un TTL.
CREATE TABLE IF NOT EXISTS users (
    thread_id       TEXT PRIMARY KEY,
    phone_number_id TEXT,
    display_name    TEXT,
    consent_at      TIMESTAMPTZ,
    guardian_name   TEXT,
    guardian_email  TEXT,
    guardian_phone  TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS users_last_seen_idx ON users (last_seen_at);

-- ---------------------------------------------------------------- progress
-- Una fila por (alumno, nodo). Borrar un usuario arrastra su progreso; borrar un
-- nodo con progreso asociado se RESTRINGE (perderia el historial del alumno).
CREATE TABLE IF NOT EXISTS progress (
    thread_id    TEXT NOT NULL REFERENCES users (thread_id) ON DELETE CASCADE,
    node_id      TEXT NOT NULL
                 REFERENCES nodes (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    status       TEXT NOT NULL DEFAULT 'pending',
    attempts     INTEGER NOT NULL DEFAULT 0,
    answer       TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (thread_id, node_id),
    CONSTRAINT progress_status_chk
        CHECK (status IN ('pending', 'sent', 'answered', 'completed', 'skipped')),
    CONSTRAINT progress_attempts_chk CHECK (attempts >= 0),
    -- Invariante: 'completed' implica fecha de fin, y una fecha de fin implica
    -- 'completed'. Sin esto acaban conviviendo filas completadas sin fecha.
    CONSTRAINT progress_completed_chk
        CHECK ((status = 'completed') = (completed_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS progress_thread_status_idx ON progress (thread_id, status);

-- -------------------------------------------------------- processed_events
-- Espejo del concepto de idempotencia de StateTable (DynamoDB): la PRIMARY KEY
-- hace el trabajo del ConditionExpression=attribute_not_exists(pk).
--
-- OJO: Postgres NO expira filas solo, a diferencia del atributo `ttl` de
-- DynamoDB. `expires_at` existe para poder barrer (limpieza oportunista:
-- DELETE FROM processed_events WHERE expires_at < now()). Ver docs/09.
CREATE TABLE IF NOT EXISTS processed_events (
    idempotency_key TEXT PRIMARY KEY,
    thread_id       TEXT,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS processed_events_expires_idx ON processed_events (expires_at);
