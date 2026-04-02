"""
T1.1.4: Set up ArgoCD for GitOps deployment

This test verifies that ArgoCD Application manifests are properly configured
for automated GitOps deployment to staging and production clusters.

RED → GREEN workflow:
1. Run this test → FAIL (argocd-apps/ missing or incomplete)
2. Create argocd-apps/ directory with Application manifests
3. Run test again → PASS
4. Complete task T1.1.4 with tracking.py
"""

import pytest
from pathlib import Path
import yaml


class TestArgoCDSetup:
    """Verify ArgoCD GitOps configuration."""

    def test_argocd_apps_directory_exists(self):
        """argocd-apps/ directory must exist."""
        dir_path = Path("argocd-apps")
        assert dir_path.exists(), "Create directory: argocd-apps/"

    def test_staging_application_exists(self):
        """ArgoCD Application for staging environment must exist."""
        app_path = Path("argocd-apps/clipsight-staging.yaml")
        assert app_path.exists(), "Create file: argocd-apps/clipsight-staging.yaml"

    def test_production_application_exists(self):
        """ArgoCD Application for production environment must exist."""
        app_path = Path("argocd-apps/clipsight-production.yaml")
        assert app_path.exists(), "Create file: argocd-apps/clipsight-production.yaml"

    def test_application_has_required_fields(self):
        """ArgoCD Application must have required fields."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            # Should be an Application CRD
            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            assert app is not None, f"Application CRD missing in {env} config"

            metadata = app.get("metadata", {})
            spec = app.get("spec", {})

            # Required metadata
            assert "name" in metadata, f"Application name missing in {env}"
            assert metadata["name"] == f"clipsight-{env}", \
                f"App name should be clipsight-{env}"

            # Required spec fields
            required_spec_fields = ["project", "source", "destination"]
            for field in required_spec_fields:
                assert field in spec, f"'{field}' missing in Application spec for {env}"

    def test_application_source_points_to_git_repo(self):
        """Application source must reference Git repository."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            source = app["spec"]["source"]
            assert "repoURL" in source, f"repoURL missing in {env}"
            assert "targetRevision" in source, f"targetRevision missing in {env}"
            assert "path" in source, f"path missing in {env}"

            # Should point to Git repo
            assert source["repoURL"].startswith("https://") or source["repoURL"].startswith("git@"), \
                f"repoURL must be valid Git URL in {env}"

    def test_application_destination_points_to_cluster_namespace(self):
        """Application destination must specify cluster URL and namespace."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            dest = app["spec"]["destination"]
            assert "server" in dest, f"destination.server missing in {env}"
            assert "namespace" in dest, f"destination.namespace missing in {env}"

            # Server should be K8s API URL
            assert dest["server"].startswith("https://"), \
                f"destination.server should be HTTPS URL in {env}"

    def test_application_sync_policy_configured(self):
        """Application must have automated sync policy."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            spec = app["spec"]
            assert "syncPolicy" in spec, f"syncPolicy missing in {env}"

            sync_policy = spec["syncPolicy"]
            assert "automated" in sync_policy, f"automated sync missing in {env}"
            assert sync_policy["automated"], f"automated sync should be true in {env}"

            # Should have prune and selfHeal
            assert "prune" in sync_policy["automated"], \
                f"automated.prune missing in {env}"
            assert "selfHeal" in sync_policy["automated"], \
                f"automated.selfHeal missing in {env}"

    def test_application_project_matches_environment(self):
        """Staging should use staging project, prod should use production."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            project = app["spec"]["project"]
            assert project == env, \
                f"Project should be '{env}' for {env} environment"

    def test_application_path_points_to_overlay(self):
        """Application source path should point to a valid overlay."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            path = app["spec"]["source"]["path"]
            # Staging can use development overlay, production uses production overlay
            expected_paths = {
                "staging": ["k8s/overlays/development", "k8s/overlays/staging"],
                "production": ["k8s/overlays/production"]
            }
            assert path in expected_paths[env], \
                f"Source path for {env} should be one of {expected_paths[env]}, got {path}"

    def test_application_health_checks_defined(self):
        """Application should have health checks for key resources."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                docs = list(yaml.safe_load_all(f))

            app = None
            for doc in docs:
                if doc and doc.get("kind") == "Application":
                    app = doc
                    break

            # Should have health check rules
            if "health" in app["spec"]:
                health = app["spec"]["health"]
                assert "healthRule" in health or len(health.get("customHealthChecks", [])) > 0, \
                    f"Health checks should be defined for {env}"

    def test_applications_are_valid_yaml(self):
        """All Application YAML files must be valid."""
        import yaml

        for env in ["staging", "production"]:
            app_file = Path(f"argocd-apps/clipsight-{env}.yaml")
            with open(app_file) as f:
                try:
                    docs = list(yaml.safe_load_all(f))
                    assert len(docs) > 0, f"Empty YAML in {env}"
                    # At least one doc should be Application
                    kinds = [doc.get("kind") for doc in docs if doc]
                    assert "Application" in kinds, \
                        f"No Application CRD found in {env}"
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {env}: {e}")

# Run with: pytest tests/gitops/test_argocd_sync.py -v
#
# Expected: Initially FAIL (red phase) until argocd-apps/ created
# After creating ArgoCD Application manifests: PASS
# Then: python scripts/tracking.py complete T1.1.4
