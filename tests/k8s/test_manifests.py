"""
T1.1.1: Convert Docker Compose services to K8s manifests

This is the FIRST test for Phase 1 Task 1.1.1.
It will FAIL until k8s/base/ manifests are created.

RED → GREEN workflow:
1. Run this test → FAIL (files don't exist)
2. Create k8s/base/ directory
3. Create minimal Deployments and Services YAML
4. Run test again → PASS
5. Complete task T1.1.1 with tracking.py
"""

import pytest
from pathlib import Path


class TestK8sManifestsExist:
    """T1.1.1: Verify K8s base manifests are created."""

    def test_base_directory_exists(self):
        """k8s/base/ directory must exist."""
        base_dir = Path("k8s/base")
        assert base_dir.exists(), "Create directory: k8s/base/"

    def test_deployments_yaml_exists(self):
        """Deployments manifest must exist."""
        deployments = Path("k8s/base/deployments.yaml")
        assert deployments.exists(), "Create file: k8s/base/deployments.yaml"

    def test_services_yaml_exists(self):
        """Services manifest must exist."""
        services = Path("k8s/base/services.yaml")
        assert services.exists(), "Create file: k8s/base/services.yaml"

    def test_configmap_yaml_exists(self):
        """ConfigMap manifest must exist for shared config."""
        configmap = Path("k8s/base/configmap.yaml")
        assert configmap.exists(), "Create file: k8s/base/configmap.yaml"


class TestK8sManifestsValid:
    """T1.1.1: Verify manifests are valid YAML with required structure."""

    @pytest.fixture
    def base_dir(self):
        return Path("k8s/base")

    def test_deployments_contains_required_services(self, base_dir):
        """All core services must have Deployment manifests."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        if not deployments_file.exists():
            pytest.fail("deployments.yaml missing - cannot validate structure")

        with open(deployments_file) as f:
            docs = list(yaml.safe_load_all(f))

        service_names = []
        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                service_names.append(doc["metadata"]["name"])

        required_services = [
            "registry",
            "main-api",
            "extractor",
            "embedder",
        ]

        for service in required_services:
            assert service in service_names, f"Deployment for '{service}' missing"

    def test_services_match_deployments(self, base_dir):
        """Every Deployment must have a corresponding Service."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        services_file = base_dir / "services.yaml"

        if not (deployments_file.exists() and services_file.exists()):
            pytest.fail("Manifests missing - create both files first")

        # Get deployment names
        with open(deployments_file) as f:
            deployment_docs = list(yaml.safe_load_all(f))
        deployment_names = [
            doc["metadata"]["name"]
            for doc in deployment_docs
            if doc and doc.get("kind") == "Deployment"
        ]

        # Get service names
        with open(services_file) as f:
            service_docs = list(yaml.safe_load_all(f))
        service_names = [
            doc["metadata"]["name"]
            for doc in service_docs
            if doc and doc.get("kind") == "Service"
        ]

        for deploy_name in deployment_names:
            assert deploy_name in service_names, \
                f"Service '{deploy_name}' missing (matches Deployment)"

    def test_configmap_contains_common_env(self, base_dir):
        """ConfigMap must have common environment variables for all services."""
        import yaml

        configmap_file = base_dir / "configmap.yaml"
        if not configmap_file.exists():
            pytest.fail("configmap.yaml missing")

        with open(configmap_file) as f:
            doc = yaml.safe_load(f)

        assert doc["kind"] == "ConfigMap"
        assert "data" in doc

        required_vars = [
            "MINIO_URL",
            "REDIS_URL",
            "REGISTRY_URL",
            "LOG_LEVEL",
        ]

        for var in required_vars:
            assert var in doc["data"], f"ConfigMap missing variable: {var}"

    def test_deployments_have_resource_requirements(self, base_dir):
        """All Deployments must specify resource limits (production readiness)."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        if not deployments_file.exists():
            pytest.fail("deployments.yaml missing")

        with open(deployments_file) as f:
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                container = doc["spec"]["template"]["spec"]["containers"][0]
                assert "resources" in container, \
                    f"Deployment '{doc['metadata']['name']}' missing resources"
                assert "requests" in container["resources"], "Missing resource requests"
                assert "limits" in container["resources"], "Missing resource limits"

    def test_deployments_have_liveness_probe(self, base_dir):
        """All deployments must have liveness probes for K8s health checks."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        if not deployments_file.exists():
            pytest.fail("deployments.yaml missing")

        with open(deployments_file) as f:
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                container = doc["spec"]["template"]["spec"]["containers"][0]
                assert "livenessProbe" in container, \
                    f"Deployment '{doc['metadata']['name']}' missing livenessProbe"
                assert "readinessProbe" in container, \
                    f"Deployment '{doc['metadata']['name']}' missing readinessProbe"

    def test_env_from_configmap_and_secret(self, base_dir):
        """Deployments must reference ConfigMap and Secret for env vars."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        if not deployments_file.exists():
            pytest.fail("deployments.yaml missing")

        with open(deployments_file) as f:
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                container = doc["spec"]["template"]["spec"]["containers"][0]
                env_from = container.get("envFrom", [])

                # Must have ConfigMapEnvSource
                has_configmap = any(
                    "configMapRef" in env_source
                    for env_source in env_from
                )
                assert has_configmap, \
                    f"Deployment '{doc['metadata']['name']}' missing configMapRef in envFrom"

    def test_services_have_selector_labels_match_deployment(self, base_dir):
        """Services must select pods by matching Deployment labels."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        services_file = base_dir / "services.yaml"

        if not (deployments_file.exists() and services_file.exists()):
            pytest.fail("Manifests missing")

        # Build mapping: deployment name -> pod labels
        with open(deployments_file) as f:
            deployment_docs = list(yaml.safe_load_all(f))

        deployment_labels = {}
        for doc in deployment_docs:
            if doc and doc.get("kind") == "Deployment":
                name = doc["metadata"]["name"]
                pod_labels = doc["spec"]["template"]["metadata"]["labels"]
                deployment_labels[name] = pod_labels

        # Check service selectors match
        with open(services_file) as f:
            service_docs = list(yaml.safe_load_all(f))

        for doc in service_docs:
            if doc and doc.get("kind") == "Service":
                service_name = doc["metadata"]["name"]
                selector = doc["spec"]["selector"]

                # Find corresponding deployment
                if service_name in deployment_labels:
                    pod_labels = deployment_labels[service_name]
                    for key, value in selector.items():
                        assert pod_labels.get(key) == value, \
                            f"Service '{service_name}' selector mismatch: {key}={value} expected, got {pod_labels}"

    def test_services_specify_ports(self, base_dir):
        """All Services must expose required ports."""
        import yaml

        services_file = base_dir / "services.yaml"
        if not services_file.exists():
            pytest.fail("services.yaml missing")

        expected_ports = {
            "registry": 8000,
            "main-api": 8080,
            "extractor": 8001,
            "embedder": 8001,  # Internal only, no need for NodePort
        }

        with open(services_file) as f:
            docs = list(yaml.safe_load_all(f))

        service_ports = {}
        for doc in docs:
            if doc and doc.get("kind") == "Service":
                name = doc["metadata"]["name"]
                ports = doc["spec"].get("ports", [])
                if ports:
                    # Get first port targetPort/port
                    service_ports[name] = ports[0].get("port") or ports[0].get("targetPort")

        for service, expected_port in expected_ports.items():
            if service in service_ports:
                assert service_ports[service] == expected_port, \
                    f"Service '{service}' port should be {expected_port}"


class TestK8sManifestsReadyForOverlay:
    """T1.1.2: Ensures base manifests are Kustomize-ready."""

    def test_manifests_have_kustomize_labels(self, base_dir):
        """K8s resources should have app.kubernetes.io labels for Kustomize."""
        import yaml

        deployments_file = base_dir / "deployments.yaml"
        if not deployments_file.exists():
            pytest.fail("deployments.yaml missing")

        with open(deployments_file) as f:
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc and doc.get("kind") in ["Deployment", "Service"]:
                labels = doc["metadata"].get("labels", {})
                assert "app.kubernetes.io/name" in labels, \
                    f"Resource {doc['metadata']['name']} missing app.kubernetes.io/name label"
                assert "app.kubernetes.io/instance" in labels, \
                    f"Resource {doc['metadata']['name']} missing app.kubernetes.io/instance label"
                assert "app.kubernetes.io/version" in labels, \
                    f"Resource {doc['metadata']['name']} missing app.kubernetes.io/version label"


# Run with: pytest tests/k8s/test_manifests.py -v
#
# Expected result: Initially FAIL (all tests red)
# After creating k8s/base/ with manifests: PASS (all tests green)
# Then run: python scripts/tracking.py complete T1.1.1
