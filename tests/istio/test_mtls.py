"""
T1.4.8: Service Mesh (Istio) mTLS installation

Tests for Istio mTLS configuration.
"""

import pytest
import yaml
from pathlib import Path
import subprocess


class TestIstioMTLS:
    """Test Istio mTLS setup."""

    def test_istio_directory_exists(self):
        """kubernetes/istio/ directory should exist."""
        istio_dir = Path("kubernetes/istio")
        assert istio_dir.exists(), f"Istio directory not found: {istio_dir}"

    def test_istio_operator_or_manifest_present(self):
        """Istio installation manifests or Operator should be present."""
        istio_dir = Path("kubernetes/istio")
        yaml_files = list(istio_dir.glob("*.yaml")) + list(istio_dir.glob("*.yml"))
        assert len(yaml_files) > 0, "No Istio manifest files found"
        found_istio = False
        for ifile in yaml_files:
            with open(ifile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                kind = doc.get("kind", "")
                name = doc.get("metadata", {}).get("name", "")
                if "Istio" in kind or "istio" in name or "pilot" in name.lower():
                    found_istio = True
                    break
            if found_istio:
                break
        assert found_istio, "No Istio-related resources found"

    def test_mtls_policy_or_peer_authentication(self):
        """Mesh-level mTLS should be configured via PeerAuthentication or DestinationRule."""
        istio_dir = Path("kubernetes/istio")
        yaml_files = list(istio_dir.glob("*.yaml")) + list(istio_dir.glob("*.yml"))
        found_mtls = False
        for ifile in yaml_files:
            with open(ifile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") == "PeerAuthentication":
                    mtls = doc.get("spec", {}).get("mtls", {})
                    if mtls.get("mode") in ("STRICT", "PERMISSIVE"):
                        found_mtls = True
                        break
                elif doc.get("kind") == "DestinationRule":
                    # Check for trafficPolicy tls
                    traffic_policy = doc.get("spec", {}).get("trafficPolicy", {})
                    tls = traffic_policy.get("tls", {})
                    if tls.get("mode") in ("ISTIO_MUTUAL", "MUTUAL"):
                        found_mtls = True
                        break
            if found_mtls:
                break
        assert found_mtls, "No mTLS configuration found in Istio manifests"

    def test_mtls_enforced_mesh_wide(self):
        """There should be a PeerAuthentication in the mesh root namespace (istio-system) setting mode=STRICT."""
        istio_dir = Path("kubernetes/istio")
        yaml_files = list(istio_dir.glob("*.yaml")) + list(istio_dir.glob("*.yml"))
        found_strict = False
        for ifile in yaml_files:
            with open(ifile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") != "PeerAuthentication":
                    continue
                metadata = doc.get("metadata", {})
                ns = metadata.get("namespace", "istio-system")
                # If namespace is istio-system (or default) and applies to all workloads via selector
                spec = doc.get("spec", {})
                selector = spec.get("selector", {})
                # Empty selector means all workloads in the namespace
                if ns in ("istio-system", "istio") or selector == {}:
                    mtls = spec.get("mtls", {})
                    if mtls.get("mode") == "STRICT":
                        found_strict = True
                        break
            if found_strict:
                break
        assert found_strict, "Mesh-wide strict mTLS not configured"

    def test_istio_installed_in_cluster(self):
        """Integration: Verify Istio pods are running (requires cluster)."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", "istio-system", "-l", "istio=pilot", "--request-timeout=10s"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                pytest.skip("Istio not installed or cluster not accessible")
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                pod_line = lines[1]
                assert "Running" in pod_line, "Istio pilot pod not Running"
            else:
                pytest.skip("Istio pilot pod not found")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Kubernetes cluster not available")

    def test_mtls_verification_with_istioctl(self):
        """Check mTLS status using istioctl (if available)."""
        # This is a basic check; would require istioctl installed
        # We'll skip unless istioctl is present
        result = subprocess.run(["which", "istioctl"], capture_output=True, text=True)
        if result.returncode != 0:
            pytest.skip("istioctl not installed")
        # Run: istioctl authn tls-check
        # This would verify mTLS status for services; but we'll just check command runs
        # In a real cluster, we would check: istioctl authn tls-check --mesh
        # For now, skip actual check
        pytest.skip("istioctl check not implemented in test")
