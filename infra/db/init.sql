-- Runs once when the Postgres volume is first created (docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Runtime role for the API/worker. It must NOT own tables or be superuser,
-- otherwise Row-Level Security is bypassed (HANDOFF 1.3). Migrations run as `raabta` (owner).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'raabta_app') THEN
    CREATE ROLE raabta_app LOGIN PASSWORD 'raabta_app' NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE raabta TO raabta_app;
GRANT USAGE ON SCHEMA public TO raabta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE raabta IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO raabta_app;
ALTER DEFAULT PRIVILEGES FOR ROLE raabta IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO raabta_app;
