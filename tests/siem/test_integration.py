"""
T1.5.5: SIEM integration (Splunk/Elastic)

Tests for SIEM integration: verify that audit logs are forwarded to Splunk/Elastic via Logstash or similar.
"""

import pytest
import yaml
from pathlib import Path
import re


class TestSIEMIntegration:
    """Test SIEM integration configuration."""

    def test_logstash_config_exists(self):
        """Logstash pipeline configuration for audit logs should exist."""
        logstash_dir = Path("kubernetes/logstash")
        if not logstash_dir.exists():
            pytest.skip("Logstash config directory not created yet")
        config_files = list(logstash_dir.glob("*.conf")) + list(logstash_dir.glob("*.yaml"))
        assert len(config_files) > 0, "No Logstash configuration files found"
        # Prefer a file named like audit or siem
        audit_configs = [f for f in config_files if "audit" in f.name.lower() or "siem" in f.name.lower()]
        if not audit_configs:
            pytest.skip("No audit-specific Logstash config found (expected naming)")

    def test_logstash_audit_pipeline_has_kafka_input(self):
        """Logstash should consume from Kafka topic 'audit-logs'."""
        logstash_dir = Path("kubernetes/logstash")
        config_files = list(logstash_dir.glob("*.conf"))
        # Look for a config with input { kafka { ... } }
        found_kafka_input = False
        for cfg_file in config_files:
            content = cfg_file.read_text()
            if "input {" in content and "kafka" in content and "audit-logs" in content:
                found_kafka_input = True
                break
        assert found_kafka_input, "No Logstash config with Kafka input for audit-logs topic"

    def test_logstash_has_siem_output(self):
        """Logstash should output to Splunk (HTTP Event Collector) or Elasticsearch."""
        logstash_dir = Path("kubernetes/logstash")
        config_files = list(logstash_dir.glob("*.conf"))
        found_output = False
        for cfg_file in config_files:
            content = cfg_file.read_text()
            # Look for output { ... http { ... } } or output { ... elasticsearch { ... } }
            if re.search(r'output\s*\{[^}]*http\s*\{', content, re.IGNORECASE | re.DOTALL) or \
               re.search(r'output\s*\{[^}]*elasticsearch\s*\{', content, re.IGNORECASE | re.DOTALL):
                found_output = True
                break
        assert found_output, "Logstash config missing output to SIEM (Splunk/Elastic)"

    def test_audit_log_retention_in_siem_policy(self):
        """SIEM retention policy should be at least 7 years (in configuration docs)."""
        # Check for documentation or config that sets retention
        docs_dir = Path("docs/operations")
        if not docs_dir.exists():
            pytest.skip("Operations docs not yet created")
        retention_doc = docs_dir / "siem-retention.md"
        if retention_doc.exists():
            content = retention_doc.read_text().lower()
            assert "7 year" in content or "seven year" in content or "7years" in content, \
                "SIEM retention policy should specify 7+ years"
        else:
            pytest.skip("SIEM retention documentation not created")

    def test_audit_log_immutability_in_transit(self):
        """Audit logs should be sent over TLS to SIEM."""
        logstash_dir = Path("kubernetes/logstash")
        config_files = list(logstash_dir.glob("*.conf"))
        for cfg_file in config_files:
            content = cfg_file.read_text()
            # If output http (Splunk HEC), should use https
            if "http" in content and "host =>" in content:
                # Look for 'ssl => true' or 'ssl => "true"'
                assert re.search(r'ssl\s*=>\s*(true|"true")', content, re.IGNORECASE), \
                    f"SSL not enabled for HTTP output in {cfg_file.name}"
            # If elasticsearch output, check for 'ssl => true'
            if "elasticsearch" in content:
                assert re.search(r'ssl\s*=>\s*(true|"true")', content, re.IGNORECASE), \
                    f"SSL not enabled for Elasticsearch output in {cfg_file.name}"
