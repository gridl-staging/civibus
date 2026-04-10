"""Contract tests for campaign-finance graph edge declarations.

Validates that graph_edges.yaml follows the plugin-contract shape, uses only
approved node labels and relationship names, and references only column names
that exist in the Stage 2 SQL schema.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SCHEMA_DIR = Path(__file__).parent.parent / "schema"
GRAPH_EDGES_PATH = SCHEMA_DIR / "graph_edges.yaml"
TABLES_SQL_PATH = SCHEMA_DIR / "tables.sql"

APPROVED_NODE_LABELS = {"Committee", "Candidate", "Filing"}

APPROVED_RELATIONSHIPS = {
    "CONTRIBUTED_TO": ("Person | Organization", "Committee"),
    "SPENT_ON": ("Committee", "Organization | Person"),
    "SUPPORTS": ("Committee", "Candidate"),
    "OPPOSES": ("Committee", "Candidate"),
    "AFFILIATED_WITH": ("Candidate", "Committee"),
    "FILED": ("Committee", "Filing"),
}

TRANSACTION_EDGE_PROPERTIES = {
    "amount",
    "transaction_date",
    "transaction_type",
    "filing_id",
    "source_record_id",
}

APPROVED_RELATIONSHIP_PROPERTIES = {
    "CONTRIBUTED_TO": TRANSACTION_EDGE_PROPERTIES,
    "SPENT_ON": TRANSACTION_EDGE_PROPERTIES,
    "SUPPORTS": TRANSACTION_EDGE_PROPERTIES,
    "OPPOSES": TRANSACTION_EDGE_PROPERTIES,
    "AFFILIATED_WITH": {
        "designation",
        "candidate_election_year",
        "fec_election_year",
        "valid_period",
        "source_record_id",
    },
    "FILED": {
        "receipt_date",
        "due_date",
        "accepted_date",
        "report_type",
        "source_record_id",
    },
}

KNOWN_INVERSE_NAMES = {
    "RECEIVED_FROM",
    "HAS_FILING",
    "FILED_BY",
    "SUPPORTED_BY",
    "OPPOSED_BY",
    "RAN_IN",
}


def _load_graph_edges() -> dict:
    return yaml.safe_load(GRAPH_EDGES_PATH.read_text())


def _extract_sql_column_names() -> set[str]:
    """Extract all column names from CREATE TABLE statements in tables.sql."""
    sql_text = TABLES_SQL_PATH.read_text()
    sql_type_keywords = r"UUID|TEXT|BOOLEAN|DATE|TIMESTAMPTZ|INTEGER|SMALLINT|NUMERIC|daterange"
    pattern = rf"^\s+(\w+)\s+(?:{sql_type_keywords})"
    return set(re.findall(pattern, sql_text, re.MULTILINE))


class TestGraphEdgesContractShape:
    def test_yaml_file_exists_and_parses(self):
        assert GRAPH_EDGES_PATH.exists(), "graph_edges.yaml must exist"
        data = _load_graph_edges()
        assert isinstance(data, dict)

    def test_top_level_keys_match_plugin_contract(self):
        data = _load_graph_edges()
        assert set(data.keys()) == {"domain", "node_labels", "relationship_types"}

    def test_domain_matches_directory_name(self):
        data = _load_graph_edges()
        assert data["domain"] == "campaign_finance"

    def test_node_labels_match_approved_set(self):
        data = _load_graph_edges()
        assert set(data["node_labels"]) == APPROVED_NODE_LABELS

    def test_relationship_names_match_approved_set(self):
        data = _load_graph_edges()
        declared_names = {r["name"] for r in data["relationship_types"]}
        assert declared_names == set(APPROVED_RELATIONSHIPS.keys())

    def test_relationship_names_are_unique(self):
        data = _load_graph_edges()
        names = [r["name"] for r in data["relationship_types"]]
        assert len(names) == len(set(names)), "Duplicate relationship names found"

    def test_no_inverse_edges(self):
        data = _load_graph_edges()
        declared_names = {r["name"] for r in data["relationship_types"]}
        inverse_found = declared_names & KNOWN_INVERSE_NAMES
        assert not inverse_found, f"Inverse edges not allowed: {inverse_found}"

    def test_relationship_directions_match_approved_design(self):
        data = _load_graph_edges()
        for rel in data["relationship_types"]:
            name = rel["name"]
            assert name in APPROVED_RELATIONSHIPS, f"Unknown relationship: {name}"
            expected_from, expected_to = APPROVED_RELATIONSHIPS[name]
            assert rel["from"] == expected_from, f"{name}: expected from={expected_from}, got from={rel['from']}"
            assert rel["to"] == expected_to, f"{name}: expected to={expected_to}, got to={rel['to']}"

    def test_declaration_does_not_claim_holds_is_unavailable(self):
        declaration_text = GRAPH_EDGES_PATH.read_text(encoding="utf-8")
        assert "HOLDS (Candidate -> Office) is dropped" not in declaration_text

    def test_each_relationship_has_required_keys(self):
        data = _load_graph_edges()
        for rel in data["relationship_types"]:
            for key in ("name", "from", "to", "properties"):
                assert key in rel, f"Relationship {rel.get('name', '?')} missing key: {key}"


class TestGraphEdgePropertyAlignment:
    def test_all_property_names_exist_in_stage2_sql(self):
        data = _load_graph_edges()
        sql_columns = _extract_sql_column_names()
        missing = []
        for rel in data["relationship_types"]:
            for prop in rel["properties"]:
                if prop not in sql_columns:
                    missing.append(f"{rel['name']}.{prop}")
        assert not missing, f"Properties not found in Stage 2 SQL: {missing}"

    def test_known_bad_property_names_are_absent(self):
        """Catch doc-example names that do not exist in Stage 2 SQL."""
        data = _load_graph_edges()
        bad_names = {"date", "filed_date", "election_cycle"}
        found_bad = []
        for rel in data["relationship_types"]:
            for prop in rel["properties"]:
                if prop in bad_names:
                    found_bad.append(f"{rel['name']}.{prop}")
        assert not found_bad, f"Doc-example property names must not appear: {found_bad}"

    def test_relationship_properties_match_approved_set(self):
        data = _load_graph_edges()
        for rel in data["relationship_types"]:
            name = rel["name"]
            actual_properties = rel["properties"]
            expected_properties = APPROVED_RELATIONSHIP_PROPERTIES[name]
            assert len(actual_properties) == len(expected_properties), (
                f"{name}: duplicate or missing properties found: {actual_properties}"
            )
            assert set(actual_properties) == expected_properties, (
                f"{name}: expected properties {sorted(expected_properties)}, got {sorted(actual_properties)}"
            )

    def test_every_edge_carries_source_record_id(self):
        """Graph-schema.md requires provenance on every edge."""
        data = _load_graph_edges()
        missing_provenance = []
        for rel in data["relationship_types"]:
            if "source_record_id" not in rel["properties"]:
                missing_provenance.append(rel["name"])
        assert not missing_provenance, f"Edges missing source_record_id for provenance: {missing_provenance}"
