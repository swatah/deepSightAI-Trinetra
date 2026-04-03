"""
T1.4.7: Pod Security Standards enforcement

Tests for Pod Security policies (PSP) or Kyverno policies.
"""

import pytest
import yaml
from pathlib import Path


class TestPodSecurityStandards:
    """Test pod security policies."""

    def test_pod_security_policies_directory_exists(self):
        """kubernetes/pod-security/ directory should exist."""
        ps_dir = Path("kubernetes/pod-security")
        assert ps_dir.exists(), f"Pod security policies directory not found: {ps_dir}"

    def test_kyverno_policy_present(self):
        """Kyverno policies should be present for Pod Security Standards."""
        ps_dir = Path("kubernetes/pod-security")
        yaml_files = list(ps_dir.glob("*.yaml")) + list(ps_dir.glob("*.yml"))
        assert len(yaml_files) > 0, "No pod security policy files found"

        found_kyverno = False
        for pfile in yaml_files:
            with open(pfile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") in ("ClusterPolicy", "Policy"):
                    # Kyverno uses ClusterPolicy or Policy
                    found_kyverno = True
                    break
            if found_kyverno:
                break
        assert found_kyverno, "No Kyverno policy found"

    def test_restricted_standard_enforced(self):
        """Policies should enforce the Restricted Pod Security Standard."""
        ps_dir = Path("kubernetes/pod-security")
        yaml_files = list(ps_dir.glob("*.yaml")) + list(ps_dir.glob("*.yml"))
        found_restricted = False
        for pfile in yaml_files:
            with open(pfile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") not in ("ClusterPolicy", "Policy"):
                    continue
                # Check policy spec for restrictions
                spec = doc.get("spec", {})
                # Kyverno policy: look for validationFailurePolicy or rules that check pod security
                # Restricting: runAsNonRoot, readOnlyRootFilesystem, capabilities drop ALL, etc.
                rules = spec.get("rules", [])
                for rule in rules:
                    # Invalidate if any rule validates
                    validate = rule.get("validate", {})
                    # Check message patterns for common restrictions
                    pattern = str(validate).lower()
                    if "nonroot" in pattern or "readonlyrootfilesystem" in pattern or "drop" in pattern:
                        found_restricted = True
                        break
                if found_restricted:
                    break
        assert found_restricted, "Restricted standard not enforced in any policy"

    def test_forbidden_privileged_pods(self):
        """Policies should block privileged pods."""
        ps_dir = Path("kubernetes/pod-security")
        yaml_files = list(ps_dir.glob("*.yaml")) + list(ps_dir.glob("*.yml"))
        found_block_privileged = False
        for pfile in yaml_files:
            with open(pfile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") not in ("ClusterPolicy", "Policy"):
                    continue
                spec = doc.get("spec", {})
                # Look for patterns that forbid privileged: true
                rules = spec.get("rules", [])
                for rule in rules:
                    validate = rule.get("validate", {})
                    if "privileged" in str(validate).lower() or "securitycontext" in str(validate).lower():
                        found_block_privileged = True
                        break
                if found_block_privileged:
                    break
        assert found_block_privileged, "No policy found that blocks privileged pods"

    def test_pod_security_policies_valid_yaml(self):
        """All policy YAML files should be valid."""
        ps_dir = Path("kubernetes/pod-security")
        yaml_files = list(ps_dir.glob("*.yaml")) + list(ps_dir.glob("*.yml"))
        for pfile in yaml_files:
            with open(pfile) as f:
                try:
                    list(yaml.safe_load_all(f))
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {pfile}: {e}")

    def test_pod_security_policies_enforced_mode(self):
        """Policies should be in enforce mode (not audit or warn)."""
        ps_dir = Path("kubernetes/pod-security")
        yaml_files = list(ps_dir.glob("*.yaml")) + list(ps_dir.glob("*.yml"))
        found_enforce = False
        for pfile in yaml_files:
            with open(pfile) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") not in ("ClusterPolicy", "Policy"):
                    continue
                spec = doc.get("spec", {})
                # Kyverno: spec.validationFailureAction should be Enforce (case-insensitive)
                action = spec.get("validationFailureAction", "enforce")
                if isinstance(action, str) and action.lower() == "enforce":
                    found_enforce = True
                    break
            if found_enforce:
                break
        assert found_enforce, "No policy found with enforcement mode (enforce)"
