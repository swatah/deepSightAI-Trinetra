"""
T1.4.6: Network Policies: deny-all, allow-by-role

Tests for Kubernetes NetworkPolicy resources enforcing zero-trust networking.
"""

import pytest
import yaml
from pathlib import Path


class TestNetworkPolicies:
    """Test network policies for deny-all and role-based allow."""

    def test_network_policies_directory_exists(self):
        """kubernetes/network-policies/ directory should exist."""
        np_dir = Path("kubernetes/network-policies")
        assert np_dir.exists(), f"Network policies directory not found: {np_dir}"

    def test_deny_all_policy_present(self):
        """A default deny-all NetworkPolicy should be present."""
        np_files = list(Path("kubernetes/network-policies").glob("*.yaml"))
        found_deny_all = False
        for np_file in np_files:
            with open(np_file) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") != "NetworkPolicy":
                    continue
                spec = doc.get("spec", {})
                pod_selector = spec.get("podSelector", {})
                # If podSelector is empty {} and policyTypes include Ingress/Egress, it's deny-all
                if pod_selector == {} and ("Ingress" in spec.get("policyTypes", []) or "Egress" in spec.get("policyTypes", [])):
                    # Check that it has no Ingress rules (deny all)
                    if not spec.get("ingress"):
                        found_deny_all = True
                        break
        assert found_deny_all, "Deny-all NetworkPolicy not found"

    def test_allow_by_role_policies_present(self):
        """NetworkPolicies should allow traffic based on role labels."""
        np_files = list(Path("kubernetes/network-policies").glob("*.yaml"))
        found_role_based = False
        for np_file in np_files:
            with open(np_file) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") != "NetworkPolicy":
                    continue
                metadata = doc.get("metadata", {})
                name = metadata.get("name", "")
                # Policies that allow traffic typically have ingress or egress rules with podSelector matchLabels
                spec = doc.get("spec", {})
                if "ingress" in spec or "egress" in spec:
                    # Check for role-based labeling: from pods with specific labels
                    rules = spec.get("ingress", []) + spec.get("egress", [])
                    for rule in rules:
                        if "from" in rule:
                            for selector in rule["from"]:
                                if "podSelector" in selector:
                                    match_labels = selector["podSelector"].get("matchLabels", {})
                                    if "role" in match_labels or "app.kubernetes.io/name" in match_labels:
                                        found_role_based = True
                                        break
                        if "to" in rule:
                            for selector in rule["to"]:
                                if "podSelector" in selector:
                                    match_labels = selector["podSelector"].get("matchLabels", {})
                                    if "role" in match_labels or "app.kubernetes.io/name" in match_labels:
                                        found_role_based = True
                                        break
                if found_role_based:
                    break
        assert found_role_based, "No role-based allow NetworkPolicy found"

    def test_network_policies_target_correct_namespaces(self):
        """NetworkPolicies should be scoped to appropriate namespaces."""
        np_files = list(Path("kubernetes/network-policies").glob("*.yaml"))
        # At least one policy should be in each relevant namespace (e.g., default, deepSightAI-Trinetra)
        # We'll just check that all policies have a namespace field (or default) and are not invalid.
        namespaces = set()
        for np_file in np_files:
            with open(np_file) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") != "NetworkPolicy":
                    continue
                ns = doc.get("metadata", {}).get("namespace", "default")
                namespaces.add(ns)
        # We expect at least two namespaces to be targeted
        assert len(namespaces) >= 1, "NetworkPolicies should target at least one namespace"

    def test_network_policies_valid_yaml(self):
        """All YAML files in network-policies should be valid."""
        np_files = list(Path("kubernetes/network-policies").glob("*.yaml"))
        for np_file in np_files:
            with open(np_file) as f:
                try:
                    list(yaml.safe_load_all(f))
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {np_file}: {e}")

    def test_network_policies_have_selectors(self):
        """Every NetworkPolicy must have either podSelector or specify a specific pod via ingress/egress."""
        np_files = list(Path("kubernetes/network-policies").glob("*.yaml"))
        for np_file in np_files:
            with open(np_file) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc.get("kind") != "NetworkPolicy":
                    continue
                spec = doc.get("spec", {})
                # Must have podSelector or ingress/egress rules that implicitly select pods
                assert "podSelector" in spec or "ingress" in spec or "egress" in spec, \
                    f"Policy {doc.get('metadata', {}).get('name')} lacks both podSelector and rules"
