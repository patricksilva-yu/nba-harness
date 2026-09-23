"""Alembic environment for the canonical PostgreSQL schema."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool


config = context.config
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    """Read the target explicitly so migrations never fall back to DuckDB."""
    url = config.get_main_option("sqlalchemy.url")
    if url and "%(POSTGRES_CONNECTION_STRING)s" not in url:
        return url
    url = os.getenv("POSTGRES_CONNECTION_STRING")
    if not url:
        raise RuntimeError("POSTGRES_CONNECTION_STRING is required to run PostgreSQL migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "pyformat"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests supply a connection with an isolated PostgreSQL schema through this
    # attribute. Normal CLI usage creates the engine from POSTGRES_CONNECTION_STRING.
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=None, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
