#!/usr/bin/env python3
"""
scripts/dsai_migrate.py - Alembic multi-tenant migration deployment tool (DEP-71).

Discovers tenant schemas in PostgreSQL and applies Alembic migrations across
all tenant schemas and public schemas during deployment.
"""

import argparse
import logging
import os
import sys
from typing import List, Optional

# Prevent model downloads if Embedder is touched during migration
os.environ.setdefault("TESTING", "1")

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from deepSightAI.Trinetra.Shared.DB import dsai_get_tenant_schemas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [dsai_migrate] %(message)s",
)
dsai_logger = logging.getLogger("dsai_migrate")


def dsai_build_alembic_config(
    dsai_config_path: str = "alembic.ini",
    dsai_database_url: Optional[str] = None,
) -> Config:
    """Construct Alembic Config object with injected database URL."""
    dsai_cfg = Config(dsai_config_path)
    if dsai_database_url:
        dsai_cfg.set_main_option("sqlalchemy.url", dsai_database_url)
    return dsai_cfg


def dsai_discover_schemas(
    dsai_database_url: str,
    dsai_target_tenant: Optional[str] = None,
) -> List[str]:
    """Connect to database and discover all tenant and system schemas."""
    if dsai_target_tenant:
        dsai_safe_tenant = "".join(c for c in dsai_target_tenant if c.isalnum() or c == "_")
        return [f"tenant_{dsai_safe_tenant}"]

    dsai_engine = create_engine(dsai_database_url)
    with dsai_engine.connect() as dsai_conn:
        dsai_schemas = dsai_get_tenant_schemas(dsai_conn)
    return dsai_schemas


def dsai_run_migrations(
    dsai_database_url: str,
    dsai_revision: str = "head",
    dsai_config_path: str = "alembic.ini",
    dsai_target_tenant: Optional[str] = None,
    dsai_dry_run: bool = False,
) -> int:
    """Execute Alembic migrations across discovered schemas."""
    dsai_logger.info("Starting Trinetra Alembic migration runner...")
    dsai_logger.info("Target revision: %s", dsai_revision)
    dsai_logger.info("Database URL: %s", dsai_database_url.split("@")[-1] if "@" in dsai_database_url else dsai_database_url)

    if dsai_target_tenant:
        os.environ["TENANT_ID"] = dsai_target_tenant

    try:
        dsai_schemas = dsai_discover_schemas(dsai_database_url, dsai_target_tenant)
        dsai_logger.info("Discovered %d schema(s) to migrate: %s", len(dsai_schemas), dsai_schemas)

        if dsai_dry_run:
            dsai_logger.info("[DRY-RUN] Would apply revision '%s' to schemas: %s", dsai_revision, dsai_schemas)
            return 0

        dsai_alembic_cfg = dsai_build_alembic_config(dsai_config_path, dsai_database_url)

        # In online mode, env.py handles iteration over discovered schemas
        command.upgrade(dsai_alembic_cfg, dsai_revision)
        dsai_logger.info("Successfully applied migrations up to revision '%s' across all schemas.", dsai_revision)
        return 0
    except Exception as dsai_err:
        dsai_logger.error("Migration failed with error: %s", dsai_err, exc_info=True)
        return 1


def dsai_main() -> None:
    """Main CLI entrypoint."""
    dsai_parser = argparse.ArgumentParser(
        description="deepSightAI-Trinetra multi-tenant migration deploy tool (DEP-71)"
    )
    dsai_parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trinetra"),
        help="PostgreSQL database connection URL",
    )
    dsai_parser.add_argument(
        "--revision",
        default="head",
        help="Alembic revision target (default: head)",
    )
    dsai_parser.add_argument(
        "--config",
        default="alembic.ini",
        help="Path to alembic.ini configuration file",
    )
    dsai_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Target single tenant schema (e.g. tenant_acme)",
    )
    dsai_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without applying changes",
    )

    dsai_args = dsai_parser.parse_args()
    dsai_exit_code = dsai_run_migrations(
        dsai_database_url=dsai_args.database_url,
        dsai_revision=dsai_args.revision,
        dsai_config_path=dsai_args.config,
        dsai_target_tenant=dsai_args.tenant_id,
        dsai_dry_run=dsai_args.dry_run,
    )
    sys.exit(dsai_exit_code)


if __name__ == "__main__":
    dsai_main()
