"""
T1.1.6: Test local k3d cluster deployment

This test verifies that the repository is ready for local k3d cluster deployment
with all necessary configurations and manifests.

RED → GREEN workflow:
1. Run this test → FAIL (k3d config incomplete)
2. Ensure all manifests, overlays, and ArgoCD apps are properly configured
3. Run test again → PASS
4. Complete task T1.1.6 with tracking.py
"""

import pytest
from pathlib import Path
import yaml
import subprocess
import shutil


class TestK3DClusterDeployment:
    """Verify k3d local cluster deployment readiness."""

    def test_k3d_binary_available(self):
        """k3d binary must be installed (or script provides it)."""
        # Skip if k3d not available (CI environments may not have it)
        if not shutil.which("k3d"):
            pytest.skip("k3d binary not installed - skip k3d cluster creation test")

        # Verify k3d is functional
        result = subprocess.run(["k3d", "--version"], capture_output=True, text=True)
        assert result.returncode == 0, "k3d must be executable"
        assert "k3d" in result.stdout.lower(), "k3d version output expected"

    def test_kubectl_binary_available(self):
        """kubectl must be installed to interact with cluster."""
        if not shutil.which("kubectl"):
            pytest.skip("kubectl binary not installed")

        result = subprocess.run(["kubectl", "version", "--client"], capture_output=True, text=True)
        assert result.returncode == 0, "kubectl must be executable"

    def test_k3d_cluster_config_exists(self):
        """Optional: k3d cluster config file should exist if cluster is pre-configured."""
        # This is informational - cluster can be created via CLI too
        config_files = list(Path(".").glob("k3d*.yaml")) + list(Path(".").glob("k3d*.yml"))
        # Not required, just informational
        pytest.skip("No k3d config file required - cluster can be created with CLI flags")

    def test_k8s_base_manifests_exist(self):
        """Base K8s manifests must exist for kustomization."""
        base_dir = Path("k8s/base")
        assert base_dir.exists(), "k8s/base/ directory must exist"
        assert (base_dir / "deployments.yaml").exists(), "deployments.yaml required"
        assert (base_dir / "services.yaml").exists(), "services.yaml required"
        assert (base_dir / "configmap.yaml").exists(), "configmap.yaml required"

    def test_development_overlay_exists(self):
        """Development overlay is used for local k3d deployment."""
        dev_dir = Path("k8s/overlays/development")
        assert dev_dir.exists(), "k8s/overlays/development/ must exist"
        assert (dev_dir / "kustomization.yaml").exists(), "kustomization.yaml required"

    def test_production_overlay_exists(self):
        """Production overlay should also exist."""
        prod_dir = Path("k8s/overlays/production")
        assert prod_dir.exists(), "k8s/overlays/production/ must exist"
        assert (prod_dir / "kustomization.yaml").exists(), "kustomization.yaml required"

    def test_overlay_can_generate_valid_manifests(self):
        """kustomize should successfully generate manifests from overlay."""
        if not shutil.which("kustomize") and not shutil.which("kubectl"):
            pytest.skip("kustomize/kubectl not available")

        # Try kubectl kustomize (kubectl includes kustomize)
        cmd = ["kubectl", "kustomize", "k8s/overlays/development"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # Try kustomize directly
            if shutil.which("kustomize"):
                result = subprocess.run(
                    ["kustomize", "build", "k8s/overlays/development"],
                    capture_output=True, text=True
                )

        assert result.returncode == 0, \
            f"kustomize build failed: {result.stderr or result.stdout}"

        # Verify generated output contains expected resources
        docs = list(yaml.safe_load_all(result.stdout))
        kinds = [doc.get("kind") for doc in docs if doc]
        assert "Deployment" in kinds, "Deployments should be generated"
        assert "Service" in kinds, "Services should be generated"
        assert "ConfigMap" in kinds or "Secret" in kinds, "ConfigMaps/Secrets should be generated"

    def test_required_services_in_overlay(self):
        """All core services must be present in the generated overlay."""
        if not shutil.which("kubectl"):
            pytest.skip("kubectl not available")

        result = subprocess.run(
            ["kubectl", "kustomize", "k8s/overlays/development"],
            capture_output=True, text=True
        )
        if result.returncode != 0 and shutil.which("kustomize"):
            result = subprocess.run(
                ["kustomize", "build", "k8s/overlays/development"],
                capture_output=True, text=True
            )

        if result.returncode != 0:
            pytest.skip("kustomize build failed, cannot check services")

        docs = list(yaml.safe_load_all(result.stdout))
        service_names = []
        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                service_names.append(doc["metadata"]["name"])

        required_services = ["registry", "main-api", "extractor", "embedder"]
        for service in required_services:
            assert service in service_names, \
                f"Service '{service}' missing from generated manifests"

    def test_helm_charts_exist_for_all_services(self):
        """Helm charts should exist for optional Helm-based deployment."""
        helm_dir = Path("helm")
        assert helm_dir.exists(), "helm/ directory should exist"
        for service in ["registry", "main-api", "extractor", "embedder"]:
            chart_dir = helm_dir / service
            assert chart_dir.exists(), f"Helm chart for {service} missing"
            assert (chart_dir / "Chart.yaml").exists(), f"Chart.yaml missing for {service}"
            assert (chart_dir / "values.yaml").exists(), f"values.yaml missing for {service}"
            assert (chart_dir / "templates").exists(), f"templates/ missing for {service}"

    def test_argocd_applications_configured(self):
        """ArgoCD applications should be configured for GitOps deployment."""
        argocd_dir = Path("argocd-apps")
        assert argocd_dir.exists(), "argocd-apps/ directory must exist"
        assert (argocd_dir / "clipsight-staging.yaml").exists(), "Staging app missing"
        assert (argocd_dir / "clipsight-production.yaml").exists(), "Production app missing"

    def test_minimal_docker_compose_for_local_dev_exists(self):
        """Optional: docker-compose.yml should exist for non-k3s local development."""
        # This is optional but helpful
        compose_files = list(Path(".").glob("docker-compose*.yml"))
        # Not a hard requirement for k3d, but good to have
        assert len(compose_files) > 0, "docker-compose file(s) recommended for local dev"

    def test_docker_test_image_builds(self):
        """Test Docker image for running tests should build successfully."""
        result = subprocess.run(
            ["docker", "build", "-t", "clipsight-test-check", "-f", "tests/Dockerfile.test", "."],
            capture_output=True, text=True
        )
        # This might fail if Docker daemon isn't running, so skip gracefully
        if result.returncode != 0:
            if "Cannot connect to the Docker daemon" in result.stderr:
                pytest.skip("Docker daemon not running")
            else:
                pytest.fail(f"Docker build failed: {result.stderr}")

    def test_all_infrastructure_tests_pass(self):
        """All infrastructure tests (k8s, helm, gitops) should pass."""
        # Run pytest on infrastructure tests
        result = subprocess.run(
            ["pytest", "tests/k8s/", "tests/helm/", "tests/gitops/", "-v", "--tb=short"],
            capture_output=True, text=True
        )
        # We expect all tests to pass for deployment readiness
        if result.returncode != 0:
            pytest.fail(
                f"Infrastructure tests failing. Fix before k3d deployment.\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    def test_deployment_documentation_exists(self):
        """Documentation for local deployment should exist."""
        # Check for deployment guide
        readme_files = list(Path(".").glob("**/README.md"))
        deployment_docs = [f for f in readme_files if "deploy" in f.name.lower()]
        # At least one deployment-related doc should exist
        assert len(deployment_docs) > 0 or any("DEPLOYMENT" in f.name for f in readme_files), \
            "Deployment documentation (DEPLOYMENT.md) should exist"


# Run with: pytest tests/k8s/test_k3d.py -v
#
# Expected: Initially may FAIL if k3d not installed or manifests incomplete
# After all manifests (k8s/base, overlays, helm, argocd) are complete: PASS
# Then: python scripts/tracking.py complete T1.1.6
#
# Note: Some tests skip if binaries (k3d, kubectl, kustomize) are not available.
# The key test "test_all_infrastructure_tests_pass" ensures all manifests are valid.
