"""
T1.5.1: Design audit log schema

Tests that the audit schema design document exists and contains required elements.
"""

import pytest
from pathlib import Path
import json


class TestAuditSchemaDesign:
    """Verify the audit log schema design document."""

    def test_design_doc_exists(self):
        """Audit schema design document must exist."""
        doc_path = Path("docs/design/audit-schema.json")
        assert doc_path.exists(), f"Design document not found at {doc_path}"

    def test_valid_json_schema(self):
        """Document must be valid JSON."""
        doc_path = Path("docs/design/audit-schema.json")
        try:
            with open(doc_path) as f:
                schema = json.load(f)
            assert isinstance(schema, dict), "Schema should be a JSON object"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}")

    def test_schema_has_required_fields(self):
        """Schema must define required audit log fields."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        required_fields = ["tenant_id", "user_id", "action", "resource", "timestamp", "outcome"]
        props = schema.get("properties", {})
        for field in required_fields:
            assert field in props, f"Schema must include '{field}' property"

    def test_schema_enums_for_action(self):
        """Action field should have enum of allowed values."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        action_prop = schema.get("properties", {}).get("action", {})
        assert "enum" in action_prop, "Action property should define allowed enum values"
        expected_actions = ["CREATE", "READ", "UPDATE", "DELETE", "LOGIN", "LOGOUT", "ACCESS", "IMPORT", "EXPORT", "SHARE", "REVOKE"]
        assert set(action_prop["enum"]) >= set(expected_actions), "Action enum should include common audit actions"

    def test_schema_enums_for_outcome(self):
        """Outcome field should have SUCCESS/FAILURE/PARTIAL."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        outcome_prop = schema.get("properties", {}).get("outcome", {})
        assert "enum" in outcome_prop, "Outcome property should define enum"
        assert set(outcome_prop["enum"]) >= {"SUCCESS", "FAILURE", "PARTIAL"}, \
            "Outcome enum must include SUCCESS, FAILURE, PARTIAL"

    def test_schema_timestamp_format(self):
        """Timestamp must be date-time format."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        ts_prop = schema.get("properties", {}).get("timestamp", {})
        assert ts_prop.get("format") == "date-time", "Timestamp should have format date-time"

    def test_schema_resource_structure(self):
        """Resource should be an object with type and id."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        resource_prop = schema.get("properties", {}).get("resource", {})
        assert resource_prop.get("type") == "object", "Resource should be an object"
        assert "type" in resource_prop.get("required", []), "Resource must require 'type'"
        assert "id" in resource_prop.get("required", []), "Resource must require 'id'"

    def test_schema_immutability_metadata(self):
        """Schema should include fields for compliance (immutability)."""
        doc_path = Path("docs/design/audit-schema.json")
        with open(doc_path) as f:
            schema = json.load(f)

        # Check for timestamp (already required) and maybe other immutability hints
        props = schema.get("properties", {})
        assert "timestamp" in props, "Schema must have timestamp for immutability"
