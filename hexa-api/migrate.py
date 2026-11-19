from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg


MIGRATIONS = (
    "001_initial.sql",
    "002_tasks.sql",
    "003_agent_templates.sql",
    "004_task_template_source.sql",
    "005_task_artifacts.sql",
    "006_conversation_execution.sql",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Hexa App API PostgreSQL migrations")
    parser.add_argument("--database-url", default=os.getenv("HEXA_DATABASE_URL", ""))
    parser.add_argument("--check", action="store_true", help="connect and verify that all migration files are readable")
    args = parser.parse_args()
    if not args.database_url or not args.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("HEXA_DATABASE_URL must be a PostgreSQL URL")
    database_url = args.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    root = Path(__file__).resolve().parent / "migrations"
    scripts = [(name, (root / name).read_text(encoding="utf-8")) for name in MIGRATIONS]
    with psycopg.connect(database_url) as connection:
        if args.check:
            connection.execute("SELECT 1")
        else:
            for name, script in scripts:
                connection.execute(script)
                print(f"applied {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
