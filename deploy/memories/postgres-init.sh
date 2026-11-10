#!/bin/bash
# The databases the vendors expect. Runs once, on an empty volume.
set -e
for db in mem0_app hindsight; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE $db"
done
