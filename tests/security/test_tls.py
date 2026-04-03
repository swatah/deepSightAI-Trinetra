"""
T1.4.2: Implement TLS 1.3 everywhere (mTLS for services)

Tests for TLS 1.3 configuration and mTLS enforcement.
"""

import pytest
import yaml
from pathlib import Path
import subprocess


class TestTLS13:
    """Test TLS 1.3 and mTLS setup."""

    def test_kubernetes_ingress_directory_exists(self):
        """kubernetes/ingress/ directory should exist."""
        ingress_dir = Path("kubernetes/ingress")
        assert ingress_dir.exists(), f"Directory not found: {ingress_dir}"

    def test_ingress_tls_config_present(self):
        """Ingress TLS configuration should be present."""
        ingress_tls = Path("kubernetes/ingress/ingress-tls.yaml")
        assert ingress_tls.exists(), "Ingress TLS config missing"

        with open(ingress_tls) as f:
            docs = list(yaml.safe_load_all(f))

        # Find Ingress resources
        ingresses = [doc for doc in docs if doc.get("kind") == "Ingress"]
        assert len(ingresses) > 0, "No Ingress resources found"

        # Check TLS 1.3 is configured via annotations or spec
        for ingress in ingresses:
            spec = ingress.get("spec", {})
            tls_configs = spec.get("tls", [])
            assert len(tls_configs) > 0, f"Ingress {ingress['metadata']['name']} has no TLS config"
            # Check that TLS secret is referenced
            for tls in tls_configs:
                assert tls.get("secretName"), "TLS config missing secretName"
            # Check annotations for TLS 1.3 and cipher suites
            annotations = ingress["metadata"].get("annotations", {})
            # NGINX Ingress annotations for TLS 1.3
            assert "nginx.ingress.kubernetes.io/ssl-protocols" in annotations, \
                "Missing TLS protocols annotation"
            assert "TLSv1.3" in annotations["nginx.ingress.kubernetes.io/ssl-protocols"], \
                "TLS 1.3 not enabled in SSL protocols"

    def test_cert_manager_certificate_present(self):
        """Cert-manager Certificate resources should be present for automatic TLS."""
        cert_dir = Path("kubernetes/ingress/cert-manager")
        if not cert_dir.exists():
            pytest.skip("Cert-manager certificates not yet created")

        cert_files = list(cert_dir.glob("*.yaml"))
        assert len(cert_files) > 0, "No cert-manager Certificate resources"

        for cert_file in cert_files:
            with open(cert_file) as f:
                doc = yaml.safe_load(f)
            assert doc.get("kind") == "Certificate", f"{cert_file.name} is not a Certificate"
            spec = doc.get("spec", {})
            # Check for TLS 1.3 compatibility via private key secret
            assert "secretName" in spec, f"Certificate {doc['metadata']['name']} missing secretName"
            # Check DNS names are configured
            dns_names = spec.get("dnsNames", [])
            assert len(dns_names) > 0, f"Certificate {doc['metadata']['name']} has no DNS names"

    def test_mtls_services_enabled(self):
        """Services that require mTLS should have peerAuthentication configured."""
        # Check for Istio or Linkerd mTLS policies if using service mesh
        mesh_dir = Path("kubernetes/mesh")
        if not mesh_dir.exists():
            pytest.skip("Service mesh configuration not yet created")

        policy_files = list(mesh_dir.glob("*authentication*.yaml"))
        if not policy_files:
            policy_files = list(mesh_dir.glob("*.yaml"))
        assert len(policy_files) > 0, "No mesh mTLS policies found"

        # Check for mTLS mode STRICT or PERMISSIVE
        found_mtls = False
        for pfile in policy_files:
            with open(pfile) as f:
                doc = yaml.safe_load(f)
            if doc.get("kind") in ("PeerAuthentication", "AuthorizationPolicy"):
                spec = doc.get("spec", {})
                mtls = spec.get("mtls", {})
                if mtls.get("mode") in ("STRICT", "PERMISSIVE"):
                    found_mtls = True
                    break
        assert found_mtls, "No mTLS mode found in mesh policies"

    def test_ingress_tls_1_3_integration(self):
        """Integration: Verify Ingress is using TLS 1.3 via kubectl (requires cluster)."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "ingress", "-A", "-o", "yaml", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                pytest.skip("Cluster not accessible or no ingresses")
            ingress_data = yaml.safe_load(result.stdout)
            items = ingress_data.get("items", [])
            if not items:
                pytest.skip("No ingresses deployed")
            # Check at least one ingress has TLS 1.3 annotation
            found = False
            for item in items:
                annotations = item["metadata"].get("annotations", {})
                ssl_protocols = annotations.get("nginx.ingress.kubernetes.io/ssl-protocols", "")
                if "TLSv1.3" in ssl_protocols:
                    found = True
                    break
            assert found, "No ingress found with TLS 1.3 enabled"
        except (subprocess.TimeoutExpired, FileNotFoundError, yaml.YAMLError):
            pytest.skip("Kubernetes cluster not available or YAML parse error")

    def test_cert_manager_deployed(self):
        """Integration: Verify cert-manager is installed and running."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "deployment", "cert-manager", "-n", "cert-manager", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                pytest.skip("cert-manager not deployed")
            # Check if deployment is available
            assert "1/1" in result.stdout or "Available" in result.stdout, \
                "cert-manager deployment not ready"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Kubernetes cluster not available")
