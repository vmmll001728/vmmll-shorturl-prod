"""Alembic migration environment -- auto-generates and runs schema migrations.

Supports dual-mode operation:
  - SQLite (local development, default)
  - PostgreSQL (production, configured via DATABASE_URL env var)

Database URL is obtained from app.config.Config.database_url at runtime.
"""
import logging

from sqlalchemy import engine_from_config, pool

from alembic import context

# -- Project imports ---------------------------------------------------------
from app.config import config as app_config
from app.models.link import Base

# Alembic Config object
alembic_config = context.config

# Set up logging manually (avoids fileConfig issues with Python 3.12+ StreamHandler)
logging.basicConfig(level=logging.WARN)
logging.getLogger("alembic").setLevel(logging.INFO)

# SQLAlchemy model metadata for autogenerate
target_metadata = Base.metadata


def get_url() -> str:
    """Return the database URL from the application config.

    Supports:
      - sqlite:///./shorturl.db    (local dev, default)
      - postgresql://user:pass@host/dbname  (production via DATABASE_URL env)
    """
    return app_config.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to a database. Useful for
    reviewing the DDL before applying it, or for generating migration SQL
    for a DBA to review.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the live database and applies migrations. Uses application
    config for the connection string so that DATABASE_URL or defaults work
    transparently.
    """
    # Override sqlalchemy.url in the section so engine_from_config picks it up
    section = alembic_config.get_section(alembic_config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
