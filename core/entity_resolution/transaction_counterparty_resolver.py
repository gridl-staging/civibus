from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.extract import extract_rows_for_matching
from core.entity_resolution.l8_regression import _normalize_address
from core.entity_resolution.scoring import score_rows
from domains.campaign_finance.ingest.filing_loader import update_transaction_contributor_identity_ids

_NC_JURISDICTION = "state/NC"
_PERSON_ROLES = ("donor",)
_ORGANIZATION_ROLES = ("vendor", "payee", "contributor")
_NC_NAME_KEY = "Name"
_NC_STREET_LINE_1_KEY = "Street Line 1"
_NC_STREET_LINE_2_KEY = "Street Line 2"
_NC_CITY_KEY = "City"
_NC_STATE_KEY = "State"
_NC_ZIP_KEY = "Zip Code"
_NC_OCCUPATION_KEY = "Profession/Job Title"
_NC_EMPLOYER_KEY = "Employer's Name/Specific Field"
_ZIP5_RE = re.compile(r"\b(\d{5})")
_STREET_NUMBER_RE = re.compile(r"^\s*(\d+)")


@dataclass(frozen=True, slots=True)
class _UnresolvedTransaction:
    transaction_id: UUID
    contributor_name_raw: str | None
    contributor_employer: str | None
    contributor_occupation: str | None
    contributor_city: str | None
    contributor_state: str | None
    contributor_zip: str | None
    raw_fields: dict[str, Any]
    transaction_role: str | None
    person_candidate_ids: set[UUID]
    organization_candidate_ids: set[UUID]


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_first_and_last_name(value: str | None) -> tuple[str | None, str | None]:
    normalized = _normalize_text(value)
    if normalized is None:
        return None, None
    parts = normalized.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _zip5(value: str | None) -> str | None:
    if value is None:
        return None
    match = _ZIP5_RE.search(value)
    if match is None:
        return None
    return match.group(1)


def _street_number(value: str | None) -> str | None:
    if value is None:
        return None
    match = _STREET_NUMBER_RE.match(value)
    if match is None:
        return None
    return match.group(1)


def _normalize_state(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    return normalized.upper()


def _source_address(
    raw_fields: dict[str, Any],
    unresolved: _UnresolvedTransaction,
    *,
    entity_type: str,
) -> str | None:
    del entity_type  # Address columns in NC are shared participant fields, not role-specific columns.
    street_line_1 = _normalize_text(raw_fields.get(_NC_STREET_LINE_1_KEY))
    street_line_2 = _normalize_text(raw_fields.get(_NC_STREET_LINE_2_KEY))
    city = _normalize_text(raw_fields.get(_NC_CITY_KEY)) or _normalize_text(unresolved.contributor_city)
    state = _normalize_state(_normalize_text(raw_fields.get(_NC_STATE_KEY)) or unresolved.contributor_state)
    raw_zip = _normalize_text(raw_fields.get(_NC_ZIP_KEY)) or _normalize_text(unresolved.contributor_zip)

    address_parts = [street_line_1, street_line_2, city, state, raw_zip]
    return ", ".join(part for part in address_parts if part) or None


def _source_identifier_key(
    raw_fields: dict[str, Any],
    unresolved: _UnresolvedTransaction,
    *,
    entity_type: str,
) -> str | None:
    del unresolved
    if entity_type == "person":
        return None
    normalized_identifier = _normalize_text(raw_fields.get("identifier_key"))
    if normalized_identifier is not None:
        return normalized_identifier
    return None


def _normalize_role(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    lowered = normalized.casefold()
    if lowered in {"donor", "receipt", "contribution", "contributor", "individual"}:
        return "person"
    if lowered in {
        "vendor",
        "payee",
        "expenditure",
        "expense",
        "non-party comm",
        "business/group/org",
    }:
        return "organization"
    return None


def _normalized_entity_type_for_transaction(unresolved: _UnresolvedTransaction) -> str | None:
    role_from_transaction = _normalize_role(unresolved.transaction_role)
    if role_from_transaction is not None:
        return role_from_transaction
    role_from_raw = _normalize_role(unresolved.raw_fields.get("transaction_role"))
    if role_from_raw is not None:
        return role_from_raw
    role_from_raw_type = _normalize_role(unresolved.raw_fields.get("Transction Type"))
    if role_from_raw_type is not None:
        return role_from_raw_type
    return None


def _name_matches(raw_fields: dict[str, Any], keys: tuple[str, ...], contributor_name: str | None) -> bool:
    if contributor_name is None:
        return False
    for key in keys:
        raw_name = _normalize_text(raw_fields.get(key))
        if raw_name is not None and raw_name.casefold() == contributor_name.casefold():
            return True
    return False


def _candidate_entity_type_scope_for_transaction(unresolved: _UnresolvedTransaction) -> set[str]:
    transaction_entity_type = _normalized_entity_type_for_transaction(unresolved)
    if transaction_entity_type is not None:
        return {transaction_entity_type}

    contributor_name = _normalize_text(unresolved.contributor_name_raw)
    source_name = _normalize_text(unresolved.raw_fields.get(_NC_NAME_KEY))
    source_name_matches = _name_matches(
        {_NC_NAME_KEY: source_name},
        (_NC_NAME_KEY,),
        contributor_name,
    )
    if source_name_matches:
        if unresolved.person_candidate_ids and not unresolved.organization_candidate_ids:
            return {"person"}
        if unresolved.organization_candidate_ids and not unresolved.person_candidate_ids:
            return {"organization"}

    return {"person", "organization"}


def _person_transaction_row(unresolved: _UnresolvedTransaction) -> dict[str, Any]:
    canonical_name = _normalize_text(unresolved.contributor_name_raw) or _normalize_text(
        unresolved.raw_fields.get(_NC_NAME_KEY)
    )
    first_name, last_name = _split_first_and_last_name(canonical_name)
    raw_address = _source_address(unresolved.raw_fields, unresolved, entity_type="person")
    normalized_address = _normalize_address(raw_address)
    employer = _normalize_text(unresolved.contributor_employer) or _normalize_text(
        unresolved.raw_fields.get(_NC_EMPLOYER_KEY)
    )
    occupation = _normalize_text(unresolved.contributor_occupation) or _normalize_text(
        unresolved.raw_fields.get(_NC_OCCUPATION_KEY)
    )
    return {
        "id": unresolved.transaction_id,
        "canonical_name": canonical_name,
        "first_name": first_name,
        "last_name": last_name,
        "last_name_prefix5": last_name[:5] if last_name is not None else None,
        "last_name_prefix3": last_name[:3] if last_name is not None else None,
        "date_of_birth": None,
        "normalized_address": normalized_address,
        "street_number": _street_number(normalized_address),
        "zip5": _zip5(unresolved.contributor_zip),
        "state": _normalize_state(unresolved.contributor_state),
        "employer": employer,
        "occupation": occupation,
        "identifier_key": _source_identifier_key(
            unresolved.raw_fields,
            unresolved,
            entity_type="person",
        ),
    }


def _organization_transaction_row(unresolved: _UnresolvedTransaction) -> dict[str, Any]:
    canonical_name = _normalize_text(unresolved.contributor_name_raw) or _normalize_text(
        unresolved.raw_fields.get(_NC_NAME_KEY)
    )
    raw_address = _source_address(unresolved.raw_fields, unresolved, entity_type="organization")
    normalized_address = _normalize_address(raw_address)
    return {
        "id": unresolved.transaction_id,
        "canonical_name": canonical_name,
        "canonical_name_soundex": None,
        "name_prefix5": canonical_name[:5] if canonical_name is not None else None,
        "registered_state": _normalize_state(unresolved.contributor_state),
        "normalized_address": normalized_address,
        "zip5": _zip5(unresolved.contributor_zip),
        "org_type": None,
        "ein": None,
        "fec_committee_id": None,
        "registered_agent_name": None,
    }


def _rows_by_entity_id(rows: list[dict[str, Any]]) -> dict[UUID, list[dict[str, Any]]]:
    indexed_rows: dict[UUID, list[dict[str, Any]]] = {}
    for row in rows:
        indexed_rows.setdefault(row["id"], []).append(row)
    return indexed_rows


def _canonical_pair(entity_id_a: UUID, entity_id_b: UUID) -> tuple[UUID, UUID]:
    if entity_id_a < entity_id_b:
        return entity_id_a, entity_id_b
    return entity_id_b, entity_id_a


def _deterministic_pairs_for_person_candidates(
    *,
    transaction_row: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transaction_id = transaction_row["id"]
    transaction_identifier_key = transaction_row.get("identifier_key")
    transaction_name = transaction_row.get("canonical_name")
    transaction_address = transaction_row.get("normalized_address")

    matched_candidate_ids: set[UUID] = set()
    for candidate_row in candidate_rows:
        candidate_id = candidate_row["id"]
        candidate_identifier_key = candidate_row.get("identifier_key")
        if transaction_identifier_key is not None and candidate_identifier_key == transaction_identifier_key:
            matched_candidate_ids.add(candidate_id)
            continue

        if (
            transaction_name is not None
            and transaction_address is not None
            and candidate_row.get("canonical_name") == transaction_name
            and candidate_row.get("normalized_address") == transaction_address
            and candidate_row.get("zip5") == transaction_row.get("zip5")
        ):
            matched_candidate_ids.add(candidate_id)

    return [
        {
            "entity_id_a": _canonical_pair(transaction_id, candidate_id)[0],
            "entity_id_b": _canonical_pair(transaction_id, candidate_id)[1],
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_transaction_counterparty_identifier",
        }
        for candidate_id in sorted(matched_candidate_ids, key=str)
    ]


def _deterministic_pairs_for_organization_candidates(
    *,
    transaction_row: dict[str, Any],
    transaction_identifier_key: str | None,
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transaction_id = transaction_row["id"]
    transaction_name = transaction_row.get("canonical_name")
    transaction_address = transaction_row.get("normalized_address")
    transaction_ein = None
    if transaction_identifier_key is not None and transaction_identifier_key.lower().startswith("ein:"):
        transaction_ein = transaction_identifier_key.split(":", 1)[1].strip()

    matched_candidate_ids: set[UUID] = set()
    for candidate_row in candidate_rows:
        candidate_id = candidate_row["id"]
        if transaction_ein is not None and _normalize_text(candidate_row.get("ein")) == transaction_ein:
            matched_candidate_ids.add(candidate_id)
            continue

        if (
            transaction_name is not None
            and transaction_address is not None
            and candidate_row.get("canonical_name") == transaction_name
            and candidate_row.get("normalized_address") == transaction_address
            and candidate_row.get("zip5") == transaction_row.get("zip5")
        ):
            matched_candidate_ids.add(candidate_id)

    return [
        {
            "entity_id_a": _canonical_pair(transaction_id, candidate_id)[0],
            "entity_id_b": _canonical_pair(transaction_id, candidate_id)[1],
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_transaction_counterparty_identifier",
        }
        for candidate_id in sorted(matched_candidate_ids, key=str)
    ]


def _extract_unresolved_nc_transactions(conn: psycopg.Connection) -> list[_UnresolvedTransaction]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                t.id AS transaction_id,
                t.contributor_name_raw,
                t.contributor_employer,
                t.contributor_occupation,
                t.contributor_city,
                t.contributor_state,
                t.contributor_zip,
                t.transaction_type,
                sr.raw_fields,
                es.entity_type,
                es.entity_id
            FROM cf.transaction t
            JOIN core.source_record sr
              ON sr.id = t.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            LEFT JOIN core.entity_source es
              ON es.source_record_id = sr.id
             AND (
                    (es.entity_type = 'person' AND es.extraction_role = ANY(%s))
                 OR (es.entity_type = 'organization' AND es.extraction_role = ANY(%s))
                 )
            WHERE LOWER(ds.jurisdiction) = LOWER(%s)
              AND t.contributor_person_id IS NULL
              AND t.contributor_organization_id IS NULL
            ORDER BY t.id
            """,
            (list(_PERSON_ROLES), list(_ORGANIZATION_ROLES), _NC_JURISDICTION),
        )
        rows = cursor.fetchall()

    unresolved_by_transaction: dict[UUID, _UnresolvedTransaction] = {}
    for row in rows:
        transaction_id = row["transaction_id"]
        unresolved = unresolved_by_transaction.get(transaction_id)
        if unresolved is None:
            unresolved = _UnresolvedTransaction(
                transaction_id=transaction_id,
                contributor_name_raw=row["contributor_name_raw"],
                contributor_employer=row["contributor_employer"],
                contributor_occupation=row["contributor_occupation"],
                contributor_city=row["contributor_city"],
                contributor_state=row["contributor_state"],
                contributor_zip=row["contributor_zip"],
                transaction_role=row["transaction_type"],
                raw_fields=dict(row["raw_fields"] or {}),
                person_candidate_ids=set(),
                organization_candidate_ids=set(),
            )
            unresolved_by_transaction[transaction_id] = unresolved

        candidate_entity_id = row["entity_id"]
        candidate_entity_type = row["entity_type"]
        if candidate_entity_id is None or candidate_entity_type is None:
            continue
        if candidate_entity_type == "person":
            unresolved.person_candidate_ids.add(candidate_entity_id)
        if candidate_entity_type == "organization":
            unresolved.organization_candidate_ids.add(candidate_entity_id)

    return list(unresolved_by_transaction.values())


def _transaction_match_candidates(
    *,
    transaction_id: UUID,
    candidate_ids: set[UUID],
    classified_pairs: list[dict[str, Any]],
) -> dict[UUID, float]:
    transaction_id_str = str(transaction_id)
    candidate_scores: dict[UUID, float] = {}
    for pair in classified_pairs:
        if pair.get("decision") != "match":
            continue
        left_id = pair["entity_id_a"]
        right_id = pair["entity_id_b"]
        if str(left_id) == transaction_id_str:
            candidate_id = right_id
        elif str(right_id) == transaction_id_str:
            candidate_id = left_id
        else:
            continue
        if candidate_id not in candidate_ids:
            continue

        confidence = float(pair["confidence"])
        previous_confidence = candidate_scores.get(candidate_id)
        if previous_confidence is None or confidence > previous_confidence:
            candidate_scores[candidate_id] = confidence
    return candidate_scores


def _resolve_best_candidate_id(
    *,
    transaction_id: UUID,
    candidate_ids: set[UUID],
    classified_pairs: list[dict[str, Any]],
) -> tuple[UUID | None, bool]:
    candidate_scores = _transaction_match_candidates(
        transaction_id=transaction_id,
        candidate_ids=candidate_ids,
        classified_pairs=classified_pairs,
    )
    if not candidate_scores:
        return None, False

    highest_confidence = max(candidate_scores.values())
    best_candidate_ids = sorted(
        (candidate_id for candidate_id, confidence in candidate_scores.items() if confidence == highest_confidence),
        key=str,
    )
    if len(best_candidate_ids) > 1:
        return None, True
    return best_candidate_ids[0], False


def _resolve_match_for_entity_type(
    conn: psycopg.Connection,
    *,
    unresolved: _UnresolvedTransaction,
    entity_type: str,
    candidate_ids: set[UUID],
    rows_by_id: dict[UUID, list[dict[str, Any]]],
    auto_merge_threshold: float | None,
) -> tuple[UUID | None, bool]:
    if not candidate_ids:
        return None, False

    candidate_rows: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        candidate_rows.extend(rows_by_id.get(candidate_id, []))
    if not candidate_rows:
        return None, False

    if entity_type == "person":
        transaction_row = _person_transaction_row(unresolved)
        deterministic_pairs = _deterministic_pairs_for_person_candidates(
            transaction_row=transaction_row,
            candidate_rows=candidate_rows,
        )
    else:
        transaction_row = _organization_transaction_row(unresolved)
        deterministic_pairs = _deterministic_pairs_for_organization_candidates(
            transaction_row=transaction_row,
            transaction_identifier_key=_source_identifier_key(
                unresolved.raw_fields,
                unresolved,
                entity_type="organization",
            ),
            candidate_rows=candidate_rows,
        )

    scored_pairs = score_rows(
        [*candidate_rows, transaction_row],
        entity_type,
        deterministic_pairs=deterministic_pairs,
    )
    classified_pairs = classify_scored_pairs(
        scored_pairs,
        auto_merge_threshold=auto_merge_threshold,
    )
    return _resolve_best_candidate_id(
        transaction_id=unresolved.transaction_id,
        candidate_ids=candidate_ids,
        classified_pairs=classified_pairs,
    )


def resolve_nc_transaction_counterparties(
    conn: psycopg.Connection,
    *,
    auto_merge_threshold: float | None = None,
) -> dict[str, int]:
    """Resolve unresolved NC transaction counterparties through the ER scoring stack."""
    unresolved_transactions = _extract_unresolved_nc_transactions(conn)
    if not unresolved_transactions:
        return {
            "candidate_transactions": 0,
            "mutated_rows": 0,
            "matched_person_rows": 0,
            "matched_organization_rows": 0,
            "skipped_rows": 0,
            "ambiguous_rows": 0,
            "dual_match_rows": 0,
        }

    person_rows_by_id = _rows_by_entity_id(extract_rows_for_matching(conn, "person"))
    organization_rows_by_id = _rows_by_entity_id(extract_rows_for_matching(conn, "organization"))

    matched_person_rows = 0
    matched_organization_rows = 0
    skipped_rows = 0
    ambiguous_rows = 0
    dual_match_rows = 0
    mutated_rows = 0

    for unresolved in unresolved_transactions:
        candidate_entity_types = _candidate_entity_type_scope_for_transaction(unresolved)
        matched_person_id, person_is_ambiguous = _resolve_match_for_entity_type(
            conn,
            unresolved=unresolved,
            entity_type="person",
            candidate_ids=(unresolved.person_candidate_ids if "person" in candidate_entity_types else set()),
            rows_by_id=person_rows_by_id,
            auto_merge_threshold=auto_merge_threshold,
        )
        matched_organization_id, organization_is_ambiguous = _resolve_match_for_entity_type(
            conn,
            unresolved=unresolved,
            entity_type="organization",
            candidate_ids=(
                unresolved.organization_candidate_ids if "organization" in candidate_entity_types else set()
            ),
            rows_by_id=organization_rows_by_id,
            auto_merge_threshold=auto_merge_threshold,
        )

        if person_is_ambiguous or organization_is_ambiguous:
            ambiguous_rows += 1
            skipped_rows += 1
            continue
        if matched_person_id is not None and matched_organization_id is not None:
            dual_match_rows += 1
            skipped_rows += 1
            continue
        if matched_person_id is None and matched_organization_id is None:
            skipped_rows += 1
            continue

        did_mutate = update_transaction_contributor_identity_ids(
            conn,
            transaction_id=unresolved.transaction_id,
            contributor_person_id=matched_person_id,
            contributor_organization_id=matched_organization_id,
        )
        if not did_mutate:
            skipped_rows += 1
            continue

        mutated_rows += 1
        if matched_person_id is not None:
            matched_person_rows += 1
        if matched_organization_id is not None:
            matched_organization_rows += 1

    return {
        "candidate_transactions": len(unresolved_transactions),
        "mutated_rows": mutated_rows,
        "matched_person_rows": matched_person_rows,
        "matched_organization_rows": matched_organization_rows,
        "skipped_rows": skipped_rows,
        "ambiguous_rows": ambiguous_rows,
        "dual_match_rows": dual_match_rows,
    }
