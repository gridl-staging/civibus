from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.entity_resolution.extract import RowDict
from core.entity_resolution.scoring import (
    filter_unresolved_rows,
    run_deterministic_rules,
)
from core.entity_resolution.test_extract import (
    _insert_organization,
    _insert_person,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_pair(pairs: list[dict], id_a: UUID, id_b: UUID) -> dict | None:
    """Find a scored pair containing both ids (canonical ordering)."""
    canonical_a = min(id_a, id_b)
    canonical_b = max(id_a, id_b)
    for pair in pairs:
        if pair["entity_id_a"] == canonical_a and pair["entity_id_b"] == canonical_b:
            return pair
    return None


def _is_pair(pair: dict, id_a: UUID, id_b: UUID) -> bool:
    canonical_a = min(id_a, id_b)
    canonical_b = max(id_a, id_b)
    return pair["entity_id_a"] == canonical_a and pair["entity_id_b"] == canonical_b


# ===========================================================================
# run_deterministic_rules — integration tests
# ===========================================================================


@pytest.mark.integration
def test_deterministic_person_fec_id_match(db_conn: psycopg.Connection) -> None:
    """Two persons sharing the same fec_id are matched deterministically."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Alice Smith",
        first_name="Alice",
        last_name="Smith",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-SHARED-001"},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Alice J Smith",
        first_name="Alice",
        last_name="Smith",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-SHARED-001"},
    )

    pairs = run_deterministic_rules(db_conn, "person")

    test_pair = _find_pair(pairs, person_a, person_b)
    assert test_pair is not None, f"Expected pair not found among {len(pairs)} pairs"
    assert test_pair["confidence"] == 1.0
    assert test_pair["decision_method"] == "deterministic"
    assert test_pair["decided_by"] == "deterministic_fec_id_match"
    assert test_pair["matched_rule_names"] == ["deterministic_fec_id_match"]
    assert test_pair["entity_id_a"] < test_pair["entity_id_b"]


@pytest.mark.integration
def test_deterministic_org_ein_match(db_conn: psycopg.Connection) -> None:
    """Two orgs sharing the same EIN are matched deterministically."""
    org_a = uuid4()
    org_b = uuid4()

    _insert_organization(
        db_conn,
        organization_id=org_a,
        canonical_name="Acme Corp",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": "12-3456789"},
    )
    _insert_organization(
        db_conn,
        organization_id=org_b,
        canonical_name="ACME Corporation",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": "12-3456789"},
    )

    pairs = run_deterministic_rules(db_conn, "organization")

    test_pair = _find_pair(pairs, org_a, org_b)
    assert test_pair is not None
    assert test_pair["confidence"] == 1.0
    assert test_pair["decision_method"] == "deterministic"
    assert test_pair["decided_by"] == "deterministic_ein_match"
    assert test_pair["matched_rule_names"] == ["deterministic_ein_match"]


@pytest.mark.integration
def test_deterministic_person_trimmed_identifier_match(db_conn: psycopg.Connection) -> None:
    """Stable identifiers match even when one record includes surrounding whitespace."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Trimmed A",
        first_name="Trimmed",
        last_name="Alpha",
        date_of_birth=None,
        identifiers={"voter_reg_id": " VR-TRIM-001 "},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Trimmed B",
        first_name="Trimmed",
        last_name="Beta",
        date_of_birth=None,
        identifiers={"voter_reg_id": "VR-TRIM-001"},
    )

    pairs = run_deterministic_rules(db_conn, "person")

    test_pair = _find_pair(pairs, person_a, person_b)
    assert test_pair is not None
    assert test_pair["decided_by"] == "deterministic_voter_reg_match"
    assert test_pair["matched_rule_names"] == ["deterministic_voter_reg_match"]


@pytest.mark.integration
def test_deterministic_org_trimmed_identifier_match(db_conn: psycopg.Connection) -> None:
    """Organization stable identifiers match even when one record includes padding."""
    org_a = uuid4()
    org_b = uuid4()

    _insert_organization(
        db_conn,
        organization_id=org_a,
        canonical_name="Trimmed Org A",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": " 98-7654321 "},
    )
    _insert_organization(
        db_conn,
        organization_id=org_b,
        canonical_name="Trimmed Org B",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": "98-7654321"},
    )

    pairs = run_deterministic_rules(db_conn, "organization")

    test_pair = _find_pair(pairs, org_a, org_b)
    assert test_pair is not None
    assert test_pair["decided_by"] == "deterministic_ein_match"
    assert test_pair["matched_rule_names"] == ["deterministic_ein_match"]


@pytest.mark.integration
def test_deterministic_null_identifier_no_match(db_conn: psycopg.Connection) -> None:
    """Persons with no fec_id (key absent from identifiers) are not matched."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="No Id One",
        first_name="No",
        last_name="One",
        date_of_birth=None,
        identifiers={"employer": "Acme"},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="No Id Two",
        first_name="No",
        last_name="Two",
        date_of_birth=None,
        identifiers={"employer": "Acme"},
    )

    pairs = run_deterministic_rules(db_conn, "person")
    assert _find_pair(pairs, person_a, person_b) is None


@pytest.mark.integration
def test_deterministic_blank_identifier_no_match(db_conn: psycopg.Connection) -> None:
    """Persons with blank/whitespace-only identifier values are not matched."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Blank Id One",
        first_name="Blank",
        last_name="One",
        date_of_birth=None,
        identifiers={"fec_id": "", "voter_reg_id": "   "},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Blank Id Two",
        first_name="Blank",
        last_name="Two",
        date_of_birth=None,
        identifiers={"fec_id": "", "voter_reg_id": "   "},
    )

    pairs = run_deterministic_rules(db_conn, "person")
    assert _find_pair(pairs, person_a, person_b) is None


@pytest.mark.integration
def test_deterministic_org_blank_identifier_no_match(db_conn: psycopg.Connection) -> None:
    """Organizations with blank/whitespace-only identifiers are not matched."""
    org_a = uuid4()
    org_b = uuid4()

    _insert_organization(
        db_conn,
        organization_id=org_a,
        canonical_name="Blank Org A",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": " ", "fec_committee_id": "   "},
    )
    _insert_organization(
        db_conn,
        organization_id=org_b,
        canonical_name="Blank Org B",
        registered_state="NC",
        org_type="llc",
        identifiers={"ein": " ", "fec_committee_id": "   "},
    )

    pairs = run_deterministic_rules(db_conn, "organization")
    assert _find_pair(pairs, org_a, org_b) is None


@pytest.mark.integration
def test_deterministic_multiple_rules_collapse_to_one_pair(
    db_conn: psycopg.Connection,
) -> None:
    """Two persons matching on both fec_id and voter_reg_id produce one pair with both rule names."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Multi Match A",
        first_name="Multi",
        last_name="MatchA",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-MULTI-001", "voter_reg_id": "VR-MULTI-001"},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Multi Match B",
        first_name="Multi",
        last_name="MatchB",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-MULTI-001", "voter_reg_id": "VR-MULTI-001"},
    )

    pairs = run_deterministic_rules(db_conn, "person")

    test_pairs = [p for p in pairs if _is_pair(p, person_a, person_b)]
    assert len(test_pairs) == 1, f"Expected exactly 1 collapsed pair, got {len(test_pairs)}"

    pair = test_pairs[0]
    assert pair["confidence"] == 1.0
    assert pair["decision_method"] == "deterministic"
    assert pair["decided_by"] == "deterministic_multi_rule"
    assert set(pair["matched_rule_names"]) == {
        "deterministic_fec_id_match",
        "deterministic_voter_reg_match",
    }


@pytest.mark.integration
def test_deterministic_canonical_ordering(db_conn: psycopg.Connection) -> None:
    """entity_id_a < entity_id_b regardless of UUID generation order."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Order A",
        first_name="Order",
        last_name="Alpha",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-ORDER-001"},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Order B",
        first_name="Order",
        last_name="Beta",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-ORDER-001"},
    )

    pairs = run_deterministic_rules(db_conn, "person")
    test_pair = _find_pair(pairs, person_a, person_b)
    assert test_pair is not None
    assert test_pair["entity_id_a"] < test_pair["entity_id_b"]


@pytest.mark.integration
def test_deterministic_no_shared_identifiers_no_match(
    db_conn: psycopg.Connection,
) -> None:
    """No shared identifiers means no deterministic match."""
    person_a = uuid4()
    person_b = uuid4()

    _insert_person(
        db_conn,
        person_id=person_a,
        canonical_name="Unique One",
        first_name="Unique",
        last_name="One",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-UNIQUE-001"},
    )
    _insert_person(
        db_conn,
        person_id=person_b,
        canonical_name="Unique Two",
        first_name="Unique",
        last_name="Two",
        date_of_birth=None,
        identifiers={"fec_id": "FEC-UNIQUE-002"},
    )

    pairs = run_deterministic_rules(db_conn, "person")
    assert _find_pair(pairs, person_a, person_b) is None


@pytest.mark.integration
def test_deterministic_invalid_entity_type_raises(db_conn: psycopg.Connection) -> None:
    """Invalid entity_type raises ValueError."""
    with pytest.raises(ValueError, match="entity_type"):
        run_deterministic_rules(db_conn, "invalid")


# ===========================================================================
# filter_unresolved_rows — unit tests (no database needed)
# ===========================================================================


def test_filter_unresolved_rows_removes_matched_entities() -> None:
    """Entities that appear in deterministic pairs are filtered out."""
    id_a = uuid4()
    id_b = uuid4()
    id_c = uuid4()

    rows: list[RowDict] = [
        {"id": id_a, "canonical_name": "A"},
        {"id": id_b, "canonical_name": "B"},
        {"id": id_c, "canonical_name": "C"},
    ]

    deterministic_pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        }
    ]

    result = filter_unresolved_rows(rows, deterministic_pairs)
    result_ids = {r["id"] for r in result}
    assert result_ids == {id_c}


def test_filter_unresolved_rows_keeps_all_when_no_pairs() -> None:
    """All rows pass through when there are no deterministic matches."""
    id_a = uuid4()
    id_b = uuid4()

    rows: list[RowDict] = [
        {"id": id_a, "canonical_name": "A"},
        {"id": id_b, "canonical_name": "B"},
    ]

    result = filter_unresolved_rows(rows, [])
    assert len(result) == 2
    assert {r["id"] for r in result} == {id_a, id_b}


def test_filter_unresolved_rows_preserves_row_shape() -> None:
    """Filtered rows retain all original columns unchanged."""
    id_a = uuid4()
    id_b = uuid4()
    id_c = uuid4()

    rows: list[RowDict] = [
        {"id": id_a, "canonical_name": "A", "first_name": "Alice", "extra": 42},
        {"id": id_b, "canonical_name": "B", "first_name": "Bob", "extra": 99},
        {"id": id_c, "canonical_name": "C", "first_name": "Carol", "extra": 7},
    ]

    deterministic_pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        }
    ]

    result = filter_unresolved_rows(rows, deterministic_pairs)
    assert len(result) == 1
    assert result[0] == {"id": id_c, "canonical_name": "C", "first_name": "Carol", "extra": 7}
