-- RoomMind local database setup (Phase 0)
-- Creates the `roommind` role and database on your existing PostgreSQL 16.
--
-- Run it yourself so your postgres superuser password stays out of any log:
--   psql -U postgres -h localhost -p 5432 -f scripts/setup_db.sql
--
-- psql will prompt for the postgres password. Safe to re-run: every step is guarded.

\set ON_ERROR_STOP on

-- 1. Role. Password matches DATABASE_URL in .env.example (local dev only).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'roommind') THEN
        CREATE ROLE roommind WITH LOGIN PASSWORD 'roommind';
        RAISE NOTICE 'created role: roommind';
    ELSE
        RAISE NOTICE 'role roommind already exists - leaving it alone';
    END IF;
END
$$;

-- 2. Database. CREATE DATABASE cannot run inside a DO block, so use \gexec.
SELECT 'CREATE DATABASE roommind OWNER roommind ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'roommind')
\gexec

GRANT ALL PRIVILEGES ON DATABASE roommind TO roommind;

\echo ''
\echo 'RoomMind DB setup complete.'
\echo 'Verify with:  psql -U roommind -h localhost -p 5432 -d roommind -c "select current_user, current_database()"'
