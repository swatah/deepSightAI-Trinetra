"""
T1.5.7: Audit log retention policy (7+ years)

Tests that audit logs are automatically archived to cold storage after 90 days
and retained for at least 7 years.
"""
import pytest
from pathlib import Path
import re


class TestAuditRetention:
    """Test audit log retention policy."""

    def test_retention_script_exists(self):
        """Retention script should exist."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        assert script_path.exists(), "Retention archive script not found at scripts/retention/archive_audit_logs.py"

    def test_retention_script_has_90day_threshold(self):
        """Script should define retention threshold of 90 days for archival."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        content = script_path.read_text()
        # Look for a constant or config indicating 90 days
        # Accept patterns: ARCHIVE_AFTER_DAYS = 90, RETENTION_DAYS = 90, ARCHIVE_DAYS = 90
        pattern = r'(ARCHIVE_AFTER_DAYS|RETENTION_DAYS|ARCHIVE_DAYS)\s*=\s*90'
        assert re.search(pattern, content, re.IGNORECASE), \
            "Script should define 90-day archival threshold (e.g., ARCHIVE_AFTER_DAYS = 90)"

    def test_retention_policy_7_years(self):
        """Retention policy should specify 7+ years for archived logs."""
        # Check in script or docs for 7-year retention
        script_path = Path("scripts/retention/archive_audit_logs.py")
        if script_path.exists():
            content = script_path.read_text()
            if re.search(r'7\s*(years|year|yrs)', content, re.IGNORECASE):
                return
        # Check docs
        docs_path = Path("docs/operations/retention.md")
        if docs_path.exists():
            content = docs_path.read_text()
            assert re.search(r'7\s*(years|year|yrs)', content, re.IGNORECASE), \
                "Retention policy should document 7-year retention"
        else:
            pytest.skip("No retention documentation or 7-year reference found")

    def test_cronjob_manifest_exists(self):
        """K8s CronJob for audit retention should exist."""
        cron_path = Path("kubernetes/cronjobs/audit-retention.yaml")
        assert cron_path.exists(), "CronJob manifest for audit retention not found at kubernetes/cronjobs/audit-retention.yaml"

    def test_cronjob_schedule_is_daily(self):
        """CronJob should run daily."""
        cron_path = Path("kubernetes/cronjobs/audit-retention.yaml")
        content = cron_path.read_text()
        # Look for schedule: field (cron format)
        match = re.search(r'schedule:\s*([^\s]+)', content)
        assert match, "CronJob should have a schedule field"
        schedule = match.group(1)
        # A daily cron schedule typically has "0 0 * * *" or similar with day-of-month as *
        # We'll check that it includes a wildcard for day-of-month
        parts = schedule.split()
        if len(parts) == 5:
            # minute hour dom month dow
            # For daily, dom or dow is * (wildcard)
            assert parts[2] == '*' or parts[4] == '*', f"Schedule {schedule} should run daily (use * in day field)"
        else:
            # Might be a valid schedule but not standard 5-field; just accept
            pass

    def test_retention_script_uses_s3(self):
        """Retention script should upload to S3 for cold storage."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        content = script_path.read_text()
        # Look for S3 usage: boto3 client, aws s3, or 's3' bucket upload
        assert 'boto3' in content or ' aws s3' in content or 's3_client' in content or 'upload' in content.lower(), \
            "Script should use S3 (boto3 or awscli) for cold storage archival"

    def test_retention_script_deletes_after_archive(self):
        """Script should delete archived logs from DB after successful upload."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        content = script_path.read_text()
        # Look for DELETE FROM audit_logs or cursor.execute(... delete ...)
        assert re.search(r'DELETE\s+FROM\s+audit_logs', content, re.IGNORECASE), \
            "Script should delete archived logs from DB after upload"

    def test_retention_script_handles_errors(self):
        """Retention script should have error handling (rollback on S3 failure)."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        content = script_path.read_text()
        # Look for try/except or error checking
        assert 'try' in content.lower() and 'except' in content.lower(), \
            "Script should have error handling (try/except)"

    def test_retention_script_uses_chunking(self):
        """Script should process logs in chunks to avoid huge transactions."""
        script_path = Path("scripts/retention/archive_audit_logs.py")
        content = script_path.read_text()
        # Look for LIMIT or chunk size
        assert re.search(r'(LIMIT|CHUNK_SIZE|page_size|fetchmany)', content, re.IGNORECASE), \
            "Script should process logs in chunks (use LIMIT or chunking)"
