"""
T1.5.6: Immutable storage (WORM) for audit logs

Tests that audit logs cannot be modified or deleted.
"""

import pytest
from pathlib import Path
import re


class TestAuditImmutability:
    """Test immutable storage for audit logs."""

    def test_audit_table_schema_exists(self):
        """The SQL definition for audit_logs table should exist."""
        sql_dir = Path("kubernetes/postgres")
        sql_files = list(sql_dir.glob("*.sql")) + list(sql_dir.glob("*.conf"))
        # Look for a file containing audit_logs table creation
        found = False
        for sql_file in sql_files:
            content = sql_file.read_text()
            # Allow optional IF NOT EXISTS clause
            if re.search(r'CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?audit_logs', content, re.IGNORECASE):
                found = True
                break
        assert found, "No SQL definition for audit_logs table found"

    def test_immutability_policy_exists(self):
        """There should be a policy to prevent UPDATE/DELETE on audit_logs."""
        sql_dir = Path("kubernetes/postgres")
        sql_files = list(sql_dir.glob("*.sql"))
        # Look for RLS policy or trigger that blocks modifications
        found_policy = False
        for sql_file in sql_files:
            content = sql_file.read_text()
            # Check for ROW LEVEL SECURITY policy that denies updates/deletes
            if re.search(r'CREATE\s+POLICY.*audit_logs.*FOR\s+UPDATE', content, re.IGNORECASE | re.DOTALL) or \
               re.search(r'CREATE\s+POLICY.*audit_logs.*FOR\s+DELETE', content, re.IGNORECASE | re.DOTALL) or \
               re.search(r'BEFORE\s+UPDATE\s+ON\s+audit_logs.*RAISE', content, re.IGNORECASE | re.DOTALL) or \
               re.search(r'BEFORE\s+DELETE\s+ON\s+audit_logs.*RAISE', content, re.IGNORECASE | re.DOTALL):
                found_policy = True
                break
        assert found_policy, "No immutability policy found for audit_logs"

    def test_audit_logs_has_primary_key(self):
        """audit_logs table should have a primary key (id) to ensure row uniqueness."""
        sql_dir = Path("kubernetes/postgres")
        sql_files = list(sql_dir.glob("*.sql"))
        found_pk = False
        for sql_file in sql_files:
            content = sql_file.read_text()
            if re.search(r'CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?audit_logs.*PRIMARY\s+KEY', content, re.IGNORECASE | re.DOTALL):
                found_pk = True
                break
        assert found_pk, "audit_logs table should have a PRIMARY KEY"

    def test_audit_logs_includes_timestamp(self):
        """audit_logs table should have a timestamp column for temporal ordering."""
        sql_dir = Path("kubernetes/postgres")
        sql_files = list(sql_dir.glob("*.sql"))
        found_ts = False
        for sql_file in sql_files:
            content = sql_file.read_text()
            if re.search(r'CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?audit_logs.*timestamp', content, re.IGNORECASE | re.DOTALL):
                found_ts = True
                break
        assert found_ts, "audit_logs table should include timestamp column"

    def test_audit_logs_row_level_security_enabled(self):
        """Row Level Security should be enabled on audit_logs if using policies."""
        sql_dir = Path("kubernetes/postgres")
        sql_files = list(sql_dir.glob("*.sql"))
        found_rls = False
        for sql_file in sql_files:
            content = sql_file.read_text()
            if re.search(r'ALTER\s+TABLE\s+audit_logs.*ENABLE\s+ROW\s+LEVEL\s+SECURITY', content, re.IGNORECASE):
                found_rls = True
                break
        assert found_rls, "Row Level Security should be enabled on audit_logs"
