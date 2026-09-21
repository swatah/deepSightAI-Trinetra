"""
Alembic migration environment for deepSightAI Trinetra.
Supports multi-tenant schema-per-tenant migration (DM-10).
"""

from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool, text
from alembic import context

from deepSightAI.Trinetra.Shared.DB import Base, dsai_get_tenant_schemas as get_tenant_schemas
from deepSightAI.Trinetra.Shared.Repositories.CameraRepository import Camera
from deepSightAI.Trinetra.Shared.Repositories.PlateRepository import PlateRead
from deepSightAI.Trinetra.Shared.Repositories.WatchlistRepository import WatchlistEntry, Alert

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_url():
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trinetra")

def run_migrations_offline() -> None:
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
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schemas = get_tenant_schemas(connection)
        for schema in schemas:
            try:
                # Ensure schema exists
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                connection.execute(text(f'SET search_path TO "{schema}", public'))
                connection.commit()

                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    version_table="alembic_version",
                    version_table_schema=schema,
                )

                with context.begin_transaction():
                    context.run_migrations()
            except Exception as e:
                # Log schema migration error and continue
                print(f"Migration error for schema {schema}: {e}")

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
