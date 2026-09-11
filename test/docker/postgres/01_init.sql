-- Init PostgreSQL mirror: estensione Oracle-compat + utente di test
CREATE EXTENSION IF NOT EXISTS orafce;

DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'testapp') THEN
      CREATE ROLE testapp LOGIN PASSWORD 'TestApp_26ai';
   END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE orabridge TO testapp;
ALTER SCHEMA public OWNER TO testapp;
ALTER SCHEMA oracle OWNER TO testapp;
GRANT USAGE ON SCHEMA oracle TO testapp;
ALTER DATABASE orabridge SET search_path TO "$user", public, oracle;
