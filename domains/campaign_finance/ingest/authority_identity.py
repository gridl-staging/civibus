"""Typed source identity and fail-closed overlap handling for shared ingest.

The coverage registry owns the legal/reporting relation.  This module only
applies that accepted relation to already-acquired source records; it never
infers authority from geography, package location, or identifier similarity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
from uuid import UUID

from domains.campaign_finance.coverage.registry import (
    AuthorityRelation,
    FilingAuthorityReference,
    PartitionedOverlappingAuthorityRelation,
)


@dataclass(frozen=True, slots=True)
class AuthorityScopedSourceRecord:
    """One provenance record with its typed filing authority and physical source."""

    source_record_id: UUID
    authority: FilingAuthorityReference
    source_name: str
    raw_fields: Mapping[str, object]


class AuthorityOverlapRefusal(ValueError):
    """Raised when accepted policy does not authorize a cross-authority merge."""


def _authority_key(authority: FilingAuthorityReference) -> tuple[str, str, str | None]:
    return authority.kind, authority.code, authority.name


def _identity_value(record: AuthorityScopedSourceRecord, key: str) -> object:
    value = record.raw_fields.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AuthorityOverlapRefusal(
            f"source record {record.source_record_id} lacks nonblank deduplication key {key!r}"
        )
    if isinstance(value, (dict, list, set)):
        raise AuthorityOverlapRefusal(
            f"source record {record.source_record_id} has non-scalar deduplication key {key!r}"
        )
    return value


def _deduplicate_partitioned_overlap(
    relation: PartitionedOverlappingAuthorityRelation,
    records: Sequence[AuthorityScopedSourceRecord],
) -> list[AuthorityScopedSourceRecord]:
    accepted_authorities = {_authority_key(authority) for authority in relation.authorities}
    record_authorities = {_authority_key(record.authority) for record in records}
    unknown_authorities = record_authorities - accepted_authorities
    if unknown_authorities:
        raise AuthorityOverlapRefusal(
            f"records include authorities outside the accepted overlap relation: {sorted(unknown_authorities)!r}"
        )

    # One authority is not a cross-authority aggregate.  Its source-local identity
    # remains owned by core.source_record and is deliberately untouched here.
    if len(record_authorities) <= 1:
        return list(records)

    deduplication = relation.deduplication
    if deduplication.disposition != "deduplicate":
        raise AuthorityOverlapRefusal("accepted authority relation refuses cross-authority combination")

    precedence = {_authority_key(item.authority): index for index, item in enumerate(relation.precedence)}
    grouped: dict[tuple[object, ...], list[AuthorityScopedSourceRecord]] = {}
    for record in records:
        identity = tuple(_identity_value(record, key) for key in deduplication.identity_keys)
        grouped.setdefault(identity, []).append(record)

    selected_ids: set[UUID] = set()
    for identity, group in grouped.items():
        group_authorities = {_authority_key(record.authority) for record in group}
        if len(group_authorities) == 1:
            selected_ids.update(record.source_record_id for record in group)
            continue

        best_rank = min(precedence[_authority_key(record.authority)] for record in group)
        winners = [record for record in group if precedence[_authority_key(record.authority)] == best_rank]
        if len(winners) != 1:
            raise AuthorityOverlapRefusal(
                f"deduplication identity {identity!r} has multiple records at the winning authority precedence"
            )
        selected_ids.add(winners[0].source_record_id)

    return [record for record in records if record.source_record_id in selected_ids]


def deduplicate_authority_overlap(
    relation: AuthorityRelation,
    records: Sequence[AuthorityScopedSourceRecord],
) -> list[AuthorityScopedSourceRecord]:
    """Apply the registry-owned relation or refuse a cross-authority combination.

    Independent/inherited relations do not authorize combining multiple authority
    record sets.  Unresolved relations always refuse.  A partitioned/overlapping
    relation may deduplicate only when it declares exact identity keys and ordered
    precedence; the registry models validate those prerequisites.
    """

    if not records:
        return []
    if relation.relation == "partitioned_overlapping":
        return _deduplicate_partitioned_overlap(relation, records)

    record_authorities = {_authority_key(record.authority) for record in records}
    if relation.relation == "unresolved" or len(record_authorities) > 1:
        raise AuthorityOverlapRefusal(
            f"authority relation {relation.relation!r} does not authorize cross-authority combination"
        )
    return list(records)


__all__ = [
    "AuthorityOverlapRefusal",
    "AuthorityScopedSourceRecord",
    "deduplicate_authority_overlap",
]
