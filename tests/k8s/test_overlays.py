"""
T1.1.2: Create Kustomize overlays for dev/prod

This test verifies that Kustomize overlays are properly structured
for different environments (development, production).

RED → GREEN workflow:
1. Run this test → FAIL (overlays missing or incomplete)
2. Create k8s/overlays/{development,production}/
3. Create kustomization.yaml files in each
4. Run test again → PASS
5. Complete task T1.1.2 with tracking.py
"""

import pytest
from pathlib import Path


class TestOverlayStructure:
    """Verify Kustomize overlay structure."""

    def test_overlays_directory_exists(self):
        """k8s/overlays/ directory must exist."""
        overlays_dir = Path("k8s/overlays")
        assert overlays_dir.exists(), "Create directory: k8s/overlays/"

    def test_development_overlay_exists(self):
        """Development overlay must exist."""
        dev_dir = Path("k8s/overlays/development")
        assert dev_dir.exists(), "Create directory: k8s/overlays/development/"

    def test_production_overlay_exists(self):
        """Production overlay must exist for enterprise deployment."""
        prod_dir = Path("k8s/overlays/production")
        assert prod_dir.exists(), "Create directory: k8s/overlays/production/"

    def test_overlay_has_kustomization_yaml(self):
        """Each overlay must have kustomization.yaml."""
        for env in ["development", "production"]:
            kust_file = Path(f"k8s/overlays/{env}/kustomization.yaml")
            assert kust_file.exists(), f"Create file: k8s/overlays/{env}/kustomization.yaml"

    def test_overlay_references_base(self):
        """Overlays must reference base manifests."""
        import yaml

        for env in ["development", "production"]:
            kust_file = Path(f"k8s/overlays/{env}/kustomization.yaml")
            with open(kust_file) as f:
                doc = yaml.safe_load(f)

            assert "bases" in doc or "resources" in doc, \
                f"Overlay {env} must reference base via 'bases' or 'resources'"

            # Check it references ../../base
            bases = doc.get("bases") or doc.get("resources", [])
            assert "../../base" in str(bases), \
                f"Overlay {env} must reference ../../base"

    def test_development_overlay_has_secrets(self):
        """Dev overlay must generate secrets for local testing."""
        import yaml

        kust_file = Path("k8s/overlays/development/kustomization.yaml")
        with open(kust_file) as f:
            doc = yaml.safe_load(f)

        assert "secretGenerator" in doc, \
            "Development overlay must have secretGenerator for test credentials"

        secrets = doc["secretGenerator"]
        assert len(secrets) > 0, "secretGenerator must not be empty"

        # Check for required secret keys
        secret_data = secrets[0].get("literals", [])
        secret_keys = [item.split("=")[0] for item in secret_data]

        required_keys = ["POSTGRES_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"]
        for key in required_keys:
            assert key in secret_keys, f"Dev secrets must include {key}"

    def test_production_overlay_has_resource_limits(self):
        """Prod overlay must customize resources for production workloads."""
        import yaml

        kust_file = Path("k8s/overlays/production/kustomization.yaml")
        with open(kust_file) as f:
            doc = yaml.safe_load(f)

        # Production should use patches or config to adjust resources
        assert any(key in doc for key in ["patches", "configurations", "patchesStrategicMerge"]), \
            "Production overlay must have resource patches/configuration"

    def test_overlays_have_distinct_names(self):
        """Dev and prod overlays must generate unique resource names."""
        import yaml

        dev_kust = Path("k8s/overlays/development/kustomization.yaml")
        prod_kust = Path("k8s/overlays/production/kustomization.yaml")

        with open(dev_kust) as f:
            dev_doc = yaml.safe_load(f)
        with open(prod_kust) as f:
            prod_doc = yaml.safe_load(f)

        # Check name suffixes differ to avoid conflicts
        dev_name = dev_doc.get("nameSuffix", "")
        prod_name = prod_doc.get("nameSuffix", "")

        assert dev_name != prod_name, \
            "Dev and prod overlays must have different nameSuffix values"

    def test_overlay_configmapmerges(self):
        """Overlays must merge/override ConfigMaps appropriately."""
        import yaml

        for env in ["development", "production"]:
            kust_file = Path(f"k8s/overlays/{env}/kustomization.yaml")
            with open(kust_file) as f:
                doc = yaml.safe_load(f)

            # Should have configMapGenerator or patches for config
            has_config = "configMapGenerator" in doc or "patches" in doc
            assert has_config, \
                f"Overlay {env} must customize configuration via configMapGenerator or patches"

    def test_overlay_namesuffix_for_dev(self):
        """Development overlay should use nameSuffix for dev resources."""
        import yaml

        kust_file = Path("k8s/overlays/development/kustomization.yaml")
        with open(kust_file) as f:
            doc = yaml.safe_load(f)

        # Dev should have nameSuffix like -dev or -staging
        name_suffix = doc.get("nameSuffix", "")
        assert name_suffix, "Development overlay should have nameSuffix for resource names"


# Run with: pytest tests/k8s/test_overlays.py -v
#
# Expected result: Initially FAIL (red phase) until overlays created
# After creating k8s/overlays/{development,production}/ with kustomization.yaml: PASS
# Then run: python scripts/tracking.py complete T1.1.2
