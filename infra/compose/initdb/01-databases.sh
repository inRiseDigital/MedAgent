#!/usr/bin/env bash
# ============================================================================
# Postgres first-boot init (runs once against an empty data dir).
# Creates the three databases (10 §2.1) and per-service least-privilege roles
# (10 §5 / NFR-10): every service has its OWN credentials; no service uses the
# superuser; PUBLIC connect is revoked everywhere.
#
# Ownership model:
#   hapi_db   -> owned by `hapi`        (HAPI alone manages its schema, 10 §9.2)
#   keycloak  -> owned by `keycloak`    (dedicated DB + creds, 02 §1)
#   app_db    -> owned by `core_api`    (Alembic-only schema mechanism, 10 §9.1)
#     agent_service  : owns only the `agent` schema (LangGraph checkpointer, 01 §3)
#     notify_service : connect + read on public (notification prefs); table-level
#                      grants are refined by Alembic migrations as tables land
# ============================================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    -- roles: one per service, no shared credentials (NFR-10)
    CREATE ROLE hapi           LOGIN PASSWORD '${HAPI_DB_PASSWORD}';
    CREATE ROLE keycloak       LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
    CREATE ROLE core_api       LOGIN PASSWORD '${CORE_API_DB_PASSWORD}';
    CREATE ROLE agent_service  LOGIN PASSWORD '${AGENT_SERVICE_DB_PASSWORD}';
    CREATE ROLE notify_service LOGIN PASSWORD '${NOTIFY_SERVICE_DB_PASSWORD}';

    -- databases
    CREATE DATABASE hapi_db  OWNER hapi;
    CREATE DATABASE keycloak OWNER keycloak;
    CREATE DATABASE app_db   OWNER core_api;

    -- least privilege: nobody connects anywhere by default
    REVOKE CONNECT ON DATABASE hapi_db  FROM PUBLIC;
    REVOKE CONNECT ON DATABASE keycloak FROM PUBLIC;
    REVOKE CONNECT ON DATABASE app_db   FROM PUBLIC;

    GRANT CONNECT ON DATABASE hapi_db  TO hapi;
    GRANT CONNECT ON DATABASE keycloak TO keycloak;
    GRANT CONNECT ON DATABASE app_db   TO core_api, agent_service, notify_service;
SQL

# app_db internals: schema-level separation between the three app services
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname app_db <<-SQL
    -- core_api owns app_db (Alembic is the only schema mechanism, 10 §9.1)
    ALTER SCHEMA public OWNER TO core_api;

    -- agent-service: isolated schema for the LangGraph checkpointer tables
    -- (created via Alembic revisions vendored from the library DDL, 10 §9.4)
    CREATE SCHEMA agent AUTHORIZATION agent_service;
    REVOKE ALL ON SCHEMA agent FROM PUBLIC;

    -- notify-service: read paths on public schema; core_api migrations grant
    -- table-level SELECT (and narrow INSERT/UPDATE where needed) as tables land
    GRANT USAGE ON SCHEMA public TO notify_service, agent_service;
    ALTER DEFAULT PRIVILEGES FOR ROLE core_api IN SCHEMA public
        GRANT SELECT ON TABLES TO notify_service;
SQL

echo "initdb: app_db / hapi_db / keycloak created with per-service roles"
