# Multi-Tenancy Data Isolation Strategy

**Task**: T1.3.1-T1.3.2
**Status**: Approved
**Last Updated**: 2026-04-03

## Overview

This document defines the multi-tenancy data isolation strategy for deepSightAI Trinetra. We need to ensure that **tenant data is completely isolated** at the database level, with zero chance of cross-tenant data leakage.

---

## Candidate Approaches

### 1. Schemas-per-Tenant (Separate PostgreSQL Schemas)

**Description**: Each tenant gets their own PostgreSQL schema (e.g., `tenant_abc123`, `tenant_xyz789`). All tables exist in each schema. Application connects with a base role and sets `search_path` per request.

**Pros**:
- Strong isolation at database level
- Easy to backup/restore single tenant (pg_dump -n tenant_abc)
- Can move tenant to different database easily (pg_dump/pg_restore)
- Per-tenant maintenance (vacuum, analyze) possible
- Clear ownership: tenant_id implicitly tied to schema name

**Cons**:
- Connection pool size multiplied by tenants (each tenant needs separate connection)
- More complex connection management (need to set search_path on every connection)
- Migrations must run across all schemas (requires dynamic SQL or tools like pgrepatch)
- Schema sprawl: 1000 tenants = 1000 schemas (management overhead)

**When to use**: Low-to-medium tenant count (< 1000), strong isolation required, per-tenant ops OK.

---

### 2. Row-Level Security (RLS) with `tenant_id` Column

**Description**: Single shared schema with `tenant_id` column on every table. PostgreSQL Row Level Security policies filter rows automatically based on `current_setting('app.current_tenant_id')`.

**Pros**:
- Single schema = simple migrations (run once)
- Connection pool not multiplied (shared pool)
- Easy to add new tenants (no DDL)
- Built-in PostgreSQL security (enforced at row level, cannot bypass)
- Can combine with connection pooling for high tenant counts

**Cons**:
- Requires session-level variable setting on every connection (`SET app.current_tenant_id = ...`)
- All queries must respect RLS (application cannot override)
- More complex to debug if RLS misconfigured
- Backups are all-or-nothing (harder to extract single tenant)
- Performance may degrade with millions of rows across all tenants

**When to use**: High tenant count (> 1000), simpler operations, strong security needed.

---

### 3. Database-per-Tenant

**Description**: Each tenant gets a completely separate PostgreSQL database.

**Pros**:
- Maximum isolation (separate processes, can move to different servers)
- Easy backups/restores per tenant
- Can scale tenants across multiple DB servers
- Per-tenant tuning possible

**Cons**:
- Connection pool explosion (pool per database)
- Migration complexity extreme (must run across N databases)
- High operational overhead (monitoring, maintenance)
- Not suitable for SaaS with many small tenants

**When to use**: Enterprise customers with dedicated instances, compliance requirements.

---

## Decision: **Schemas-per-Tenant** with Connection Pooling

We choose **schemas-per-tenant** for deepSightAI Trinetra because:

1. **Moderate tenant count**: We expect < 1000 tenants in early phases
2. **Strong isolation**: Schema separation provides clear boundaries
3. **Tenant-level operations**: Ability to pg_dump/restore a single tenant is valuable for migrations and support
4. **Compliance**: Easier to demonstrate data isolation to auditors
5. **Simplicity**: No need to modify every query to include `tenant_id`; RLS policies can do it, but schemas are more explicit

---

## Implementation Strategy

### Schema Creation

When a new tenant is provisioned (`scripts/provision-tenant.sh`):

```sql
-- Create schema for tenant
CREATE SCHEMA IF NOT EXISTS "tenant_<tenant_id>";

-- Run migrations in that schema
-- Using Alembic with --schema parameter or dynamic SQL
```

### Connection Management

Application uses `shared.db.get_tenant_connection(tenant_id)` to obtain a SQLAlchemy engine configured for that tenant's schema.

Implementation (`shared/db.py`):

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

# Base connection string (without database/schema)
BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/deepSightAI-Trinetra")

# Connection pool for all tenants (shared)
_engine_pool = {}

def get_tenant_connection(tenant_id: str):
    """
    Get a SQLAlchemy engine configured for the given tenant's schema.

    Uses connection pool with options to set search_path on checkout.
    """
    if tenant_id not in _engine_pool:
        # Create engine with execution options to set search_path
        engine = create_engine(
            BASE_DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=300,
            # Use connect event to set search_path for each connection
            connect_args={
                "options": f"-c search_path=tenant_{tenant_id},public"
            }
        )
        _engine_pool[tenant_id] = engine
    return _engine_pool[tenant_id]
```

Alternative using event listeners:

```python
from sqlalchemy import event

def _set_search_path(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET search_path TO tenant_{tenant_id}, public")
    cursor.close()

engine = create_engine(BASE_DATABASE_URL)
event.listen(engine, "connect", _set_search_path)
```

---

## Database Schema Structure

All tenant schemas contain the same table structure defined in `AuthService/auth_service.py`:

```sql
-- In schema tenant_abc123
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    ...
);

CREATE TABLE tenants (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    ...
);

-- ... other tables
```

**Note**: The `tenants` table exists in **each tenant schema** but also may exist in a separate `master` or `public` schema for global tenant registry.

---

## Repository Pattern

All repository classes must use `get_tenant_connection(tenant_id)` to obtain their session:

```python
from shared.db import get_tenant_connection
from sqlalchemy.orm import Session

class VideoRepository:
    def __init__(self, tenant_id: str):
        engine = get_tenant_connection(tenant_id)
        self.Session = sessionmaker(bind=engine)

    def list_videos(self):
        with self.Session() as session:
            return session.query(Video).all()
```

---

## Migration Strategy

We'll use **Alembic** with multi-schema support:

```python
# alembic/env.py - modified for multi-tenant
def run_migrations_online():
    # Get all tenant schemas
    tenant_ids = get_all_tenant_ids()  # from tenants registry

    for tenant_id in tenant_ids:
        # create engine with tenant schema
        engine = create_tenant_engine(tenant_id)
        # run migrations for this tenant
        with engine.connect() as conn:
            context.configure(conn=conn, version_table_schema=tenant_id)
            with context.begin_transaction():
                context.run_migrations()
```

For new tenants, `provision-tenant.sh` runs migrations immediately after schema creation.

---

## Testing Strategy

- Unit tests use SQLite in-memory with separate databases per test
- Integration tests verify:
  - Schema isolation (tenant A cannot see tenant B's data)
  - Connection pooling works correctly
  - Migrations apply cleanly to new schema
- Use `pytest` fixtures to create/drop tenant schemas as needed

---

## Security Considerations

- **Never** use `search_path` without validating `tenant_id` (prevent injection)
- Use parameterized `tenant_id` in `SET search_path` command (do not interpolate raw user input)
- Connection pool should be per-tenant to avoid accidental cross-tenant reuse without proper `search_path`
- Log all connection attempts with tenant_id for audit

---

## Fallback Plan

If schemas-per-tenant proves too complex at scale, we can switch to **Row-Level Security**:

1. Keep `tenant_id` column on all tables
2. Enable RLS: `ALTER TABLE videos ENABLE ROW LEVEL SECURITY`
3. Create policy: `CREATE POLICY tenant_isolation ON videos USING (tenant_id = current_setting('app.current_tenant_id')::uuid)`
4. Application sets `SET app.current_tenant_id = '<tenant_id>'` on each connection

This provides similar isolation with less connection pool pressure.

---

## Acceptance Criteria

- [x] Design document exists with comparison of approaches
- [x] Chosen approach documented with reasoning
- [x] SQL code examples included
- [ ] `shared.db.get_tenant_connection(tenant_id)` implemented
- [ ] Integration tests verify tenant isolation
- [ ] All repositories use tenant-aware connections
- [ ] Tenant provisioning script creates schema and runs migrations

---

## Next Steps

1. Implement `shared/db.py` with `get_tenant_connection()`
2. Update all repository classes to use tenant-aware connections
3. Add database connection pooling per tenant
4. Implement `provision-tenant.sh` script (T1.3.7)
5. Test cross-tenant data leak prevention (T1.3.3)
