#!/bin/bash
# Runs once on first Postgres boot: create per-service databases and their
# pytest counterparts. (Existing volumes: create these by hand — init
# scripts only run on a fresh data volume.)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ${POSTGRES_DB}_test OWNER ${POSTGRES_USER};
    CREATE DATABASE question OWNER ${POSTGRES_USER};
    CREATE DATABASE question_test OWNER ${POSTGRES_USER};
EOSQL
