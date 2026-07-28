-- Registro de migraciones aplicadas. Se ejecuta SIEMPRE y antes que el resto:
-- es IF NOT EXISTS, asi que re-aplicarlo es inocuo.
--
-- `checksum` permite detectar que alguien edito una migracion ya aplicada. El
-- runner aborta en ese caso en vez de ignorarlo: es como los entornos derivan
-- unos de otros sin que nadie se entere.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
