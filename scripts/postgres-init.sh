#!/bin/sh
# zebaro-core-pg, first start only (docker-entrypoint-initdb.d): one database and one role per
# consumer. A role owns its database and cannot connect to the other one: CONNECT is taken from
# PUBLIC. The passwords come from the compose environment (GitHub environment `prod`).
set -eu

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v core_pw="$ZEBARO_CORE_DB_PASSWORD" -v mcp_pw="$ZEBARO_MCP_DB_PASSWORD" <<'SQL'
CREATE ROLE zebaro_core LOGIN PASSWORD :'core_pw';
CREATE DATABASE zebaro_core OWNER zebaro_core;
REVOKE CONNECT ON DATABASE zebaro_core FROM PUBLIC;

CREATE ROLE zebaro_mcp LOGIN PASSWORD :'mcp_pw';
CREATE DATABASE zebaro_mcp OWNER zebaro_mcp;
REVOKE CONNECT ON DATABASE zebaro_mcp FROM PUBLIC;
\connect zebaro_mcp
CREATE EXTENSION IF NOT EXISTS vector;
SQL
