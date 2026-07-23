"""Lookup helpers for FEC committee and candidate identifiers."""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import psycopg
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core.people.federal_officeholders import active_federal_candidate_scope_cte
from domains.campaign_finance.ingest.text_utils import normalize_optional_text


class FederalOfficeholderFecLinkPolicy(BaseModel):
    """Source-backed correction when roster FEC identifiers are insufficient."""

    model_config = ConfigDict(frozen=True)

    bioguide_id: str
    candidate_ids: tuple[str, ...]
    disposition: Literal["relink", "documented_absence"]
    source_url: str
    reason: str
    review_condition: str

    @field_validator("bioguide_id")
    @classmethod
    def validate_bioguide_id(cls, value: str) -> str:
        if re.fullmatch(r"[A-Z][0-9]{6}", value) is None:
            raise ValueError("bioguide_id must use the stable Bioguide identifier format")
        return value

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_ids must be unique")
        if any(re.fullmatch(r"[HSP][0-9][A-Z0-9]{2}[0-9]{5}", candidate_id) is None for candidate_id in value):
            raise ValueError("candidate_ids must use the stable FEC candidate identifier format")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc not in {"www.fec.gov", "fec.gov"}:
            raise ValueError("source_url must be an official HTTPS FEC URL")
        return value

    @field_validator("reason", "review_condition")
    @classmethod
    def validate_explanation(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy explanations must not be blank")
        return value

    @model_validator(mode="after")
    def validate_disposition(self) -> FederalOfficeholderFecLinkPolicy:
        if self.disposition == "relink" and not self.candidate_ids:
            raise ValueError("relink policies require at least one candidate ID")
        if self.disposition == "documented_absence" and self.candidate_ids:
            raise ValueError("documented absences cannot carry candidate IDs")
        return self


_FEDERAL_OFFICEHOLDER_FEC_LINK_POLICIES = (
    FederalOfficeholderFecLinkPolicy(
        bioguide_id="G000602",
        candidate_ids=("H2NY04244",),
        disposition="relink",
        source_url="https://www.fec.gov/data/candidate/H2NY04244/",
        reason="Current NY-04 House filing replaces stale upstream candidate H4NY04158.",
        review_condition="Review when the roster publishes the current ID, the FEC assigns a replacement, or service ends.",
    ),
    FederalOfficeholderFecLinkPolicy(
        bioguide_id="I000058",
        candidate_ids=("H2MD04232",),
        disposition="relink",
        source_url="https://www.fec.gov/data/candidate/H2MD04232/",
        reason="Current MD-04 House filing replaces stale upstream candidate H2MD04315.",
        review_condition="Review when the roster publishes the current ID, the FEC assigns a replacement, or service ends.",
    ),
    FederalOfficeholderFecLinkPolicy(
        bioguide_id="S001224",
        candidate_ids=("H2TX00064",),
        disposition="relink",
        source_url="https://www.fec.gov/data/candidate/H2TX00064/",
        reason="Current TX-03 House filing replaces stale upstream candidate H2TX03290.",
        review_condition="Review when the roster publishes the current ID, the FEC assigns a replacement, or service ends.",
    ),
    FederalOfficeholderFecLinkPolicy(
        bioguide_id="A000383",
        candidate_ids=(),
        disposition="documented_absence",
        source_url=("https://www.fec.gov/data/candidates/?q=Alan+Armstrong&election_year=2026&cycle=2026"),
        reason="The appointed Oklahoma senator has no current FEC candidate filing.",
        review_condition="Review when a current Senate/OK filing appears or the appointed officeholding ends.",
    ),
)
_FEDERAL_OFFICEHOLDER_FEC_LINK_POLICY_BY_BIOGUIDE = {
    policy.bioguide_id: policy for policy in _FEDERAL_OFFICEHOLDER_FEC_LINK_POLICIES
}
if len(_FEDERAL_OFFICEHOLDER_FEC_LINK_POLICY_BY_BIOGUIDE) != len(_FEDERAL_OFFICEHOLDER_FEC_LINK_POLICIES):
    raise ValueError("federal officeholder FEC link policy has duplicate Bioguide IDs")


def federal_officeholder_fec_link_policy(
    bioguide_id: str | None,
) -> FederalOfficeholderFecLinkPolicy | None:
    if not bioguide_id:
        return None
    return _FEDERAL_OFFICEHOLDER_FEC_LINK_POLICY_BY_BIOGUIDE.get(bioguide_id)


def resolve_federal_officeholder_fec_candidate_ids(
    *,
    bioguide_id: str | None,
    upstream_candidate_ids: Iterable[str],
) -> list[str]:
    """Put policy IDs first while retaining every unique upstream roster ID."""
    policy = federal_officeholder_fec_link_policy(bioguide_id)
    policy_candidate_ids = policy.candidate_ids if policy is not None else ()
    resolved_ids: list[str] = []
    for candidate_id in (*policy_candidate_ids, *upstream_candidate_ids):
        normalized_candidate_id = normalize_optional_text(candidate_id)
        if (
            normalized_candidate_id
            and re.fullmatch(r"[HSP][0-9][A-Z0-9]{2}[0-9]{5}", normalized_candidate_id) is not None
            and normalized_candidate_id not in resolved_ids
        ):
            resolved_ids.append(normalized_candidate_id)
    return resolved_ids


def find_committee_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.committee WHERE fec_committee_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def find_committee_ids_by_fec_ids(
    conn: psycopg.Connection,
    fec_ids: Iterable[str],
) -> dict[str, UUID]:
    """Resolve committee UUIDs for unique, non-empty FEC committee IDs."""
    committee_fec_ids: list[str] = []
    seen_committee_fec_ids: set[str] = set()
    for fec_id in fec_ids:
        normalized_fec_id = normalize_optional_text(fec_id)
        if normalized_fec_id is None or normalized_fec_id in seen_committee_fec_ids:
            continue
        seen_committee_fec_ids.add(normalized_fec_id)
        committee_fec_ids.append(normalized_fec_id)
    if not committee_fec_ids:
        return {}

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT fec_committee_id, id
            FROM cf.committee
            WHERE fec_committee_id = ANY(%s)
            """,
            (committee_fec_ids,),
        )
        rows: Iterable[tuple[str, UUID]] = cursor.fetchall()
    return {fec_committee_id: committee_id for fec_committee_id, committee_id in rows}


def find_candidate_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.candidate WHERE fec_candidate_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def current_federal_officeholder_committee_fec_ids(conn: psycopg.Connection) -> frozenset[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            WITH {active_federal_candidate_scope_cte()},
            linked_committees AS (
                SELECT cm.fec_committee_id
                FROM active_federal_candidates active
                JOIN cf.candidate_committee_link ccl ON ccl.candidate_id = active.id
                JOIN cf.committee cm ON cm.id = ccl.committee_id
                WHERE ccl.designation IN ('P', 'A')
                  AND cm.committee_designation IS DISTINCT FROM 'J'
            ),
            principal_committees AS (
                SELECT cm.fec_committee_id
                FROM active_federal_candidates active
                JOIN cf.committee cm ON cm.id = active.principal_committee_id
                WHERE cm.committee_designation IS DISTINCT FROM 'J'
            )
            SELECT DISTINCT fec_committee_id
            FROM (
                SELECT fec_committee_id FROM linked_committees
                UNION ALL
                SELECT fec_committee_id FROM principal_committees
            ) committees
            WHERE fec_committee_id IS NOT NULL
            """,
        )
        rows: Iterable[tuple[str]] = cursor.fetchall()
    return frozenset(row[0] for row in rows if row[0])


__all__ = [
    "FederalOfficeholderFecLinkPolicy",
    "current_federal_officeholder_committee_fec_ids",
    "federal_officeholder_fec_link_policy",
    "find_committee_id_by_fec_id",
    "find_committee_ids_by_fec_ids",
    "find_candidate_id_by_fec_id",
    "resolve_federal_officeholder_fec_candidate_ids",
]
