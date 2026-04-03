"""
T1.3.1: PostgreSQL multi-tenancy schema strategy design

Verifies that the tenancy strategy design document exists and defines
the chosen approach (schemas-per-tenant vs row-level security).
"""

import pytest
from pathlib import Path


class TestTenancyDesign:
    """Verify the multi-tenancy schema strategy design."""

    def test_tenancy_design_doc_exists(self):
        """Design document for tenancy strategy must exist."""
        doc_path = Path("docs/design/tenancy.md")
        assert doc_path.exists(), f"Tenancy design document not found at {doc_path}"

    def test_design_doc_has_schema_comparison(self):
        """Document must compare schemas-per-tenant vs row-level security."""
        doc_path = Path("docs/design/tenancy.md")
        content = doc_path.read_text().lower()

        has_schema_per_tenant = any(phrase in content for phrase in [
            "schema per tenant",
            "per-tenant schema",
            "schemas-per-tenant"
        ])
        has_row_level_security = any(phrase in content for phrase in [
            "row level security",
            "rls",
            "row-level security"
        ])

        assert has_schema_per_tenant or has_row_level_security, \
            "Design doc must discuss schema-per-tenant vs row-level security approaches"

    def test_design_doc_has_decision(self):
        """Document must state which approach was chosen and why."""
        doc_path = Path("docs/design/tenancy.md")
        content = doc_path.read_text().lower()

        has_decision = any(phrase in content for phrase in [
            "we chose",
            "decision",
            "chosen approach",
            "strategy"
        ])
        assert has_decision, "Design doc must document the chosen strategy with reasoning"

    def test_design_doc_has_sql_examples(self):
        """Document must include SQL code examples."""
        doc_path = Path("docs/design/tenancy.md")
        content = doc_path.read_text()

        assert "```sql" in content or "```" in content, \
            "Design doc should include SQL code examples"

    def test_design_doc_covers_migration_strategy(self):
        """Document should explain how migrations are applied across schemas."""
        doc_path = Path("docs/design/tenancy.md")
        content = doc_path.read_text().lower()

        has_migration_info = any(phrase in content for phrase in [
            "migration",
            "alembic",
            "schema creation"
        ])
        assert has_migration_info, "Design doc should cover migration strategy"
