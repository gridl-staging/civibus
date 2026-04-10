-- One-time AGE bootstrap for first deploy initialization.
-- postgres entrypoint executes initdb scripts only for a fresh PGDATA volume.
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus') THEN
        PERFORM ag_catalog.create_graph('civibus');
    END IF;
END
$$;
