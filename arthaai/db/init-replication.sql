-- Replication role for the HA standby (see docker-compose.ha.yml).
--
-- Applied by the Postgres entrypoint only on first init of an empty primary data
-- volume. The password here matches the dev default used by docker-compose.ha.yml;
-- in production it MUST come from Vault / a managed secret store, not this file.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'replicator') THEN
        CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'arthaai_repl_pw';
    END IF;
END; $$;
