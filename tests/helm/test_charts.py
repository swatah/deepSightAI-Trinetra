"""
T1.1.3: Package each service as Helm chart

This test validates that all services have valid Helm charts
that can be installed with `helm install`.

RED → GREEN workflow:
1. Run this test → FAIL (charts missing or invalid)
2. Create helm/ directory with chart for each service
3. Ensure charts have required templates and values
4. Run `helm lint` on each chart
5. Run test again → PASS
6. Complete task T1.1.3 with tracking.py
"""

import pytest
import subprocess
from pathlib import Path


class TestHelmCharts:
    """Verify Helm chart structure and validity."""

    def test_helm_directory_exists(self):
        """helm/ directory must exist."""
        helm_dir = Path("helm")
        assert helm_dir.exists(), "Create directory: helm/"

    def test_each_service_has_chart(self):
        """Each core service must have a Helm chart."""
        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            chart_dir = Path(f"helm/{service}")
            assert chart_dir.exists(), f"Create chart directory: helm/{service}/"

    def test_chart_has_required_files(self):
        """Each chart must have Chart.yaml, values.yaml, templates/."""
        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            base_path = Path(f"helm/{service}")

            # Chart.yaml
            chart_yaml = base_path / "Chart.yaml"
            assert chart_yaml.exists(), f"Missing Chart.yaml in helm/{service}/"

            # values.yaml
            values_yaml = base_path / "values.yaml"
            assert values_yaml.exists(), f"Missing values.yaml in helm/{service}/"

            # templates directory
            templates_dir = base_path / "templates"
            assert templates_dir.exists(), f"Missing templates/ in helm/{service}/"

    def test_chart_yaml_valid(self):
        """Chart.yaml must have required fields."""
        import yaml

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            chart_path = Path(f"helm/{service}/Chart.yaml")
            with open(chart_path) as f:
                chart = yaml.safe_load(f)

            assert "apiVersion" in chart, f"Chart.yaml missing apiVersion in {service}"
            assert "name" in chart, f"Chart.yaml missing name in {service}"
            assert "version" in chart, f"Chart.yaml missing version in {service}"
            assert "description" in chart, f"Chart.yaml missing description in {service}"

            # Chart name should match service
            assert chart["name"] == service, \
                f"Chart name '{chart['name']}' should match service '{service}'"

    def test_values_yaml_has_required_fields(self):
        """values.yaml must define image, replicas, resources."""
        import yaml

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            values_path = Path(f"helm/{service}/values.yaml")
            with open(values_path) as f:
                values = yaml.safe_load(f)

            # Must have image configuration
            assert "image" in values, f"values.yaml missing 'image' in {service}"
            assert "repository" in values["image"], \
                f"image.repository missing in {service}"
            assert "tag" in values["image"], \
                f"image.tag missing in {service}"

            # Must have replica count
            assert "replicaCount" in values, f"replicaCount missing in {service}"
            assert isinstance(values["replicaCount"], int), \
                f"replicaCount must be integer in {service}"

            # Must have resources defined
            assert "resources" in values, f"resources missing in {service}"
            assert "requests" in values["resources"], \
                f"resources.requests missing in {service}"
            assert "limits" in values["resources"], \
                f"resources.limits missing in {service}"

    def test_templates_include_deployment_and_service(self):
        """Each chart must have deployment.yaml and service.yaml in templates."""
        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            templates_path = Path(f"helm/{service}/templates")

            deployment = templates_path / "deployment.yaml"
            service_file = templates_path / "service.yaml"

            assert deployment.exists(), \
                f"Missing deployment.yaml in helm/{service}/templates/"
            assert service_file.exists(), \
                f"Missing service.yaml in helm/{service}/templates/"

    def test_templates_are_valid_yaml(self):
        """All template files must be valid YAML (renderable)."""
        import yaml

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            templates_path = Path(f"helm/{service}/templates")

            for template_file in templates_path.glob("*.yaml"):
                with open(template_file) as f:
                    try:
                        # Load to check syntax (doesn't render with values)
                        content = f.read()
                        if "{{" in content:
                            # Contains templates, skip full validation
                            continue
                        yaml.safe_load(content)
                    except yaml.YAMLError as e:
                        pytest.fail(f"Invalid YAML in {template_file}: {e}")

    def test_chart_lints_successfully(self):
        """All charts must pass `helm lint` without errors."""
        import shutil
        if not shutil.which("helm"):
            pytest.skip("helm binary not found")

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            chart_path = f"helm/{service}"

            # Run helm lint
            result = subprocess.run(
                ["helm", "lint", chart_path],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                pytest.fail(f"Helm lint failed for {service}:\n{result.stderr}")

    def test_chart_packages_successfully(self):
        """All charts must package into a .tgz without errors."""
        import shutil
        if not shutil.which("helm"):
            pytest.skip("helm binary not found")

        import tarfile
        import tempfile

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            chart_path = f"helm/{service}"

            with tempfile.TemporaryDirectory() as tmpdir:
                # Run helm package
                result = subprocess.run(
                    ["helm", "package", chart_path, "--destination", tmpdir],
                    capture_output=True,
                    text=True
                )

                if result.returncode != 0:
                    pytest.fail(f"Helm package failed for {service}:\n{result.stderr}")

                # Verify that a .tgz file was created
                packages = list(Path(tmpdir).glob("*.tgz"))
                assert len(packages) == 1, \
                    f"Expected one package for {service}, got {len(packages)}"

                # Verify the tarball contains expected files
                with tarfile.open(packages[0], "r:gz") as tar:
                    names = tar.getnames()
                    assert any(f"{service}/Chart.yaml" in name for name in names), \
                        f"Package missing Chart.yaml for {service}"
                    assert any(f"{service}/values.yaml" in name for name in names), \
                        f"Package missing values.yaml for {service}"
                    assert any(f"{service}/templates/" in name for name in names), \
                        f"Package missing templates/ for {service}"

    def test_values_have_common_config(self):
        """All charts should support common config: logLevel, metrics."""
        import yaml

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            values_path = Path(f"helm/{service}/values.yaml")
            with open(values_path) as f:
                values = yaml.safe_load(f)

            # Should have config for common environment variables
            # These map to the ConfigMap we created
            assert "config" in values, \
                f"values.yaml missing 'config' section in {service}"

            common_vars = ["LOG_LEVEL", "REDIS_URL", "MINIO_URL"]
            config_vars = values.get("config", {})

            for var in common_vars:
                assert var in config_vars, \
                    f"config.{var} missing in {service} values.yaml"

    def test_services_match_k8s_base(self):
        """Chart templates should produce resources consistent with k8s/base/."""
        import yaml
        import subprocess
        import shutil

        if not shutil.which("helm"):
            pytest.skip("helm binary not found")

        services = ["registry", "main-api", "extractor", "embedder"]
        for service in services:
            chart_path = f"helm/{service}"

            # Render chart with helm template
            result = subprocess.run(
                ["helm", "template", chart_path],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                pytest.fail(f"helm template failed for {service}: {result.stderr}")

            docs = list(yaml.safe_load_all(result.stdout))

            # Find Deployment and Service
            deploy = None
            svc = None
            for doc in docs:
                if not doc:
                    continue
                kind = doc.get("kind")
                name = doc.get("metadata", {}).get("name")
                if kind == "Deployment" and name == service:
                    deploy = doc
                if kind == "Service" and name == service:
                    svc = doc

            assert deploy is not None, f"Deployment '{service}' not found in rendered output"
            assert svc is not None, f"Service '{service}' not found in rendered output"

            # Service should select pods by app label
            assert "selector" in svc["spec"]
            assert svc["spec"]["selector"]["app"] == service


# Run with: pytest tests/helm/test_charts.py -v
#
# Expected: Initially FAIL (all tests red)
# After creating valid Helm charts for each service: PASS
# Then: python scripts/tracking.py complete T1.1.3
