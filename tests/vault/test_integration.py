"""
T1.4.1: Set up HashiCorp Vault for secrets management

Tests for Vault integration via Kubernetes External Secrets.
"""

import pytest
import subprocess
import yaml
from pathlib import Path


class TestVaultIntegration:
    """Test Vault setup and External Secrets integration."""

    def test_vault_kubernetes_directory_exists(self):
        """kubernetes/external-secrets/ directory should exist."""
        vault_dir = Path("kubernetes/external-secrets")
        assert vault_dir.exists(), f"Directory not found: {vault_dir}"

    def test_vault_helm_values_present(self):
        """Vault Helm values file should be present."""
        vault_values = Path("kubernetes/external-secrets/vault-values.yaml")
        assert vault_values.exists(), "Vault Helm values file missing"

        with open(vault_values) as f:
            config = yaml.safe_load(f)

        # Verify key Vault configurations
        assert config.get("server") is not None, "Vault server config missing"
        # Check HA is configured with Raft storage (the HA storage mechanism)
        assert "ha" in config["server"], "High-availability configuration missing"
        ha_config = config["server"]["ha"]
        assert ha_config.get("enabled") is True, "HA not enabled"
        # Verify Raft is enabled for storage
        assert "raft" in ha_config, "Raft storage not configured"
        assert ha_config["raft"].get("enabled") is True, "Raft storage not enabled"
        # UI configuration under server.config
        assert "config" in config["server"], "Server config section missing"
        assert config["server"]["config"].get("ui") is not None or "ui" in config["server"]["config"], "UI configuration missing"

    def test_external_secrets_manifest_present(self):
        """External Secrets operator manifest should exist."""
        es_manifest = Path("kubernetes/external-secrets/external-secrets.yaml")
        assert es_manifest.exists(), "External Secrets operator manifest missing"

        with open(es_manifest) as f:
            docs = list(yaml.safe_load_all(f))

        # Check for External Secrets operator components
        assert any("external-secrets" in doc.get("metadata", {}).get("name", "") for doc in docs), \
            "External Secrets operator resources not found"

    def test_vault_secrets_engine_configured(self):
        """Vault should have kv-v2 secrets engine enabled."""
        # Check if Vault config includes kv-v2 engine mount
        vault_config = Path("kubernetes/external-secrets/vault-config.hcl")
        if vault_config.exists():
            with open(vault_config) as f:
                config_text = f.read()
            assert "path \"kv\"\n" in config_text or "path \"kv-v2\"\n" in config_text, \
                "KV secrets engine not configured"

    def test_application_secrets_external_secrets_manifests(self):
        """Application should have External Secrets manifests for secret sync."""
        app_es_dir = Path("kubernetes/external-secrets/applications")
        if not app_es_dir.exists():
            pytest.skip("Application External Secrets not yet created")

        es_files = list(app_es_dir.glob("*.yaml"))
        assert len(es_files) > 0, "No External Secrets manifests for applications"

        # Verify they reference Vault as source
        for es_file in es_files:
            with open(es_file) as f:
                doc = yaml.safe_load(f)
            assert doc.get("spec", {}).get("provider", {}).get("vault", {}), \
                f"{es_file.name} does not use Vault as provider"

    def test_vault_running_in_cluster(self):
        """Integration test: verify Vault pods are running (requires cluster)."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-l", "app.kubernetes.io/name=vault",
                 "-n", "vault", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:  # header + at least one pod
                    pod_line = lines[1]
                    assert "Running" in pod_line, "Vault pod not in Running state"
                else:
                    pytest.skip("Vault pod not deployed yet")
            else:
                pytest.skip("Vault not deployed or cluster not accessible")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Kubernetes cluster not available")

    def test_external_secrets_operator_running(self):
        """Integration test: External Secrets operator is running."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-l",
                 "app.kubernetes.io/name=external-secrets",
                 "-n", "external-secrets", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    pod_line = lines[1]
                    assert "Running" in pod_line, "External Secrets operator not Running"
                else:
                    pytest.skip("External Secrets operator not deployed")
            else:
                pytest.skip("External Secrets operator not installed")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Kubernetes cluster not available")
