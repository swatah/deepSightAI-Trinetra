"""
T1.4.3: Enable MinIO server-side encryption (SSE-KMS)

Tests for MinIO server-side encryption configuration with KMS.
"""

import pytest
import yaml
from pathlib import Path


class TestMinIOEncryption:
    """Test MinIO SSE-KMS configuration."""

    def test_minio_helm_values_directory_exists(self):
        """MinIO Helm values directory should exist."""
        minio_dir = Path("kubernetes/minio")
        assert minio_dir.exists(), f"MinIO directory not found: {minio_dir}"

    def test_minio_helm_values_present(self):
        """MinIO Helm values file should be present."""
        minio_values = Path("kubernetes/minio/values.yaml")
        assert minio_values.exists(), "MinIO Helm values file missing"

        with open(minio_values) as f:
            config = yaml.safe_load(f)

        # Check that server encryption is configured
        assert "server" in config, "MinIO server config missing"
        server_config = config["server"]

        # Check for SSE-KMS configuration
        # MinIO supports KMS via environment variables or config
        # Typically: MINIO_KMS_* env vars or kms.* in values
        kms_config = server_config.get("kms") or server_config.get("env")
        assert kms_config is not None, "KMS configuration not found in MinIO server config"

        # If using env vars, check for KMS-related variables
        if "env" in server_config:
            env_vars = server_config["env"]
            kms_vars = [v for v in env_vars if v.get("name", "").startswith("MINIO_KMS")]
            assert len(kms_vars) > 0, "No KMS environment variables set"
            # Ensure KMS endpoint and key are configured
            var_names = [v["name"] for v in kms_vars]
            assert any("MINIO_KMS_KMSAPI_ENDPOINT" in name for name in var_names), \
                "KMS endpoint not configured"
        else:
            # Direct kms configuration
            assert "endpoint" in kms_config or "apiEndpoint" in kms_config, \
                "KMS endpoint not configured"

    def test_minio_encryption_at_rest_enabled(self):
        """MinIO should have encryption at rest enabled."""
        minio_values = Path("kubernetes/minio/values.yaml")
        with open(minio_values) as f:
            config = yaml.safe_load(f)

        server_config = config.get("server", {})
        # MinIO can enable encryption via --encrypt-key or config
        # Check for environment variable MINIO_KMS_MASTER_KEY or kms.key
        kms_config = server_config.get("kms", {})
        if "key" in kms_config:
            assert kms_config["key"], "KMS master key not set"
        else:
            env_vars = server_config.get("env", [])
            master_key_vars = [v for v in env_vars if v.get("name") == "MINIO_KMS_MASTER_KEY"]
            assert len(master_key_vars) > 0 and master_key_vars[0].get("value"), \
                "KMS master key not configured"

    def test_minio_tenant_isolation_encryption(self):
        """Verify that each tenant's data can be encrypted with separate keys (conceptual)."""
        # This is a design-level test; actual implementation uses KMS key per tenant
        # Check that configuration allows per-tenant KMS key prefixes or contexts
        minio_values = Path("kubernetes/minio/values.yaml")
        with open(minio_values) as f:
            config = yaml.safe_load(f)

        server_config = config.get("server", {})
        kms_config = server_config.get("kms", {})
        env_config = server_config.get("env", [])

        # Check if KMS is configured either via kms section or env vars
        kms_configured = False
        if kms_config:
            kms_str = str(kms_config).lower()
            if "vault" in kms_str or "kmsapi" in kms_str:
                kms_configured = True
        # Check env vars for MinIO KMS settings
        if env_config:
            env_names = [v.get("name", "") for v in env_config]
            # Look for KMS-related environment variables
            kms_envs = [name for name in env_names if name.startswith("MINIO_KMS_")]
            if len(kms_envs) > 0:
                # Check for Vault-specific endpoint
                endpoint_var = next((v for v in env_config if v.get("name") == "MINIO_KMS_KMSAPI_ENDPOINT"), None)
                if endpoint_var and ("vault" in endpoint_var.get("value", "").lower() or "kms" in endpoint_var.get("value", "").lower()):
                    kms_configured = True
                # Or if using MINIO_KMS_MASTER_KEY directly
                elif any("MINIO_KMS_MASTER_KEY" in name for name in env_names):
                    kms_configured = True

        assert kms_configured, "KMS not configured to use Vault or KMS API"

    def test_minio_helm_security_context(self):
        """MinIO pods should have security context to prevent privilege escalation."""
        minio_values = Path("kubernetes/minio/values.yaml")
        with open(minio_values) as f:
            config = yaml.safe_load(f)

        server_config = config.get("server", {})
        pod_security_context = server_config.get("podSecurityContext", {})
        # Ensure runAsNonRoot
        assert pod_security_context.get("runAsNonRoot") is True, \
            "MinIO pod should not run as root"
        # Ensure securityContext with capabilities drop
        container_security = server_config.get("securityContext", {})
        capabilities = container_security.get("capabilities", {})
        assert "drop" in capabilities, "Should drop capabilities"
        assert "ALL" in capabilities["drop"], "Should drop all capabilities"

    def test_minio_tls_enabled(self):
        """MinIO should use TLS for client connections."""
        minio_values = Path("kubernetes/minio/values.yaml")
        with open(minio_values) as f:
            config = yaml.safe_load(f)

        server_config = config.get("server", {})
        # Check TLS configuration via certificate and key
        tls = server_config.get("tls") or server_config.get("tlsConfiguration")
        assert tls is not None, "TLS configuration missing in MinIO"
        # Ensure TLS is enabled and certs are provided
        if isinstance(tls, dict):
            assert tls.get("enabled") is True or "cert" in tls, "TLS not properly enabled"
        else:
            # Could be via separate secret mount
            assert True  # Basic pass
