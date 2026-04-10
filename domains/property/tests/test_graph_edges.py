"""Contract tests for property graph edge declarations."""

from __future__ import annotations

from pathlib import Path

import yaml

SCHEMA_DIR = Path(__file__).parent.parent / "schema"
GRAPH_EDGES_PATH = SCHEMA_DIR / "graph_edges.yaml"

EXPECTED_RELATIONSHIP_DIRECTIONS = {
    "OWNS": ("Person | Organization", "Parcel"),
    "LOCATED_IN": ("Parcel", "Jurisdiction"),
    "ZONED_AS": ("Parcel", "ZoningClass"),
    "ASSESSED_AT": ("Parcel", "Assessment"),
}

EXPECTED_TEMPORAL_PROPERTY_BY_EDGE = {
    "OWNS": "ownership_recorded_at",
    "LOCATED_IN": "effective_at",
    "ZONED_AS": "zoned_at",
    "ASSESSED_AT": "assessed_at",
}


def _load_graph_edges() -> dict:
    return yaml.safe_load(GRAPH_EDGES_PATH.read_text(encoding="utf-8"))


def test_graph_edges_yaml_exists_and_parses() -> None:
    assert GRAPH_EDGES_PATH.exists(), "graph_edges.yaml must exist"
    assert isinstance(_load_graph_edges(), dict)


def test_graph_edges_domain_is_property() -> None:
    data = _load_graph_edges()
    assert data["domain"] == "property"


def test_graph_edges_node_labels_are_unique() -> None:
    data = _load_graph_edges()
    node_labels = data["node_labels"]

    assert len(node_labels) == len(set(node_labels))


def test_graph_edges_relationship_names_are_unique() -> None:
    data = _load_graph_edges()
    names = [relationship["name"] for relationship in data["relationship_types"]]

    assert len(names) == len(set(names))


def test_graph_edges_relationship_directions_match_stage1_property_sketch() -> None:
    data = _load_graph_edges()
    declared = {r["name"]: (r["from"], r["to"]) for r in data["relationship_types"]}

    assert declared == EXPECTED_RELATIONSHIP_DIRECTIONS


def test_graph_edges_include_source_record_id_and_relationship_temporal_property() -> None:
    data = _load_graph_edges()

    for relationship in data["relationship_types"]:
        name = relationship["name"]
        properties = set(relationship["properties"])
        assert "source_record_id" in properties
        assert EXPECTED_TEMPORAL_PROPERTY_BY_EDGE[name] in properties
