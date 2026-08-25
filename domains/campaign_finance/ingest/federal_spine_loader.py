"""Federal congress-spine loader.

Implements ``load_federal_spine()`` — Stage 3's primary deliverable. Materializes
exactly one ``core.person`` per current federal official (House + Senate +
delegates + President + VP), one current ``civic.officeholding`` per person, and
authoritatively repoints every matching ``cf.candidate.person_id`` by FEC
candidate ID — for ALL FIVE buckets — so member money attaches to the spine
person.

House and Senate rows flow directly into the existing
``load_federal_house_officeholders`` / ``load_federal_senate_officeholders``
owners — NOT forked. Delegate / President / VP each get a small dedicated path
modeled on the same upsert idioms (source_record → person → officeholding).

The convergence UPDATE

    UPDATE cf.candidate
    SET    person_id = %s
    WHERE  fec_candidate_id = ANY(%s)
      AND  (person_id IS NULL OR person_id <> %s)

is idempotent by construction: re-running cannot create duplicates or alter
values once every matching ``cf.candidate`` row already points at the spine
person. ``cf.candidate.updated_at`` is maintained by the existing
``trg_candidate_updated_at`` trigger (``domains/campaign_finance/schema/tables.sql``).

Convergence has a second half, added 2026-08-19 for civibus-5lm: the same FEC
candidate ids also repoint ``civic.candidacy.person_id`` via
``_converge_spine_candidacies``. Repairing only the money side left the race
page linking its incumbent to a person row with no money on it.

And a third, added 2026-08-20 to finish civibus-5lm: after everything the
FEC-only shadow person row pointed at has been repointed, the row itself is
absorbed into the spine person by ``_absorb_fec_shadow_persons`` — provenance
links moved, observed FEC name forms kept as variants, duplicate row deleted —
so /search stops returning two persons for one official and the shadow's empty
/person/ page stops existing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

import psycopg

from core.db import merge_person_identifiers
from core.db_ingest import find_person_by_identifier
from core.entity_resolution.candidacy_merge import repoint_candidacy_person
from core.types.python.models import DataSource, ValidDateRange
from domains.civics.types.models import Officeholding
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.congress_legislators_adapter import (
    AdaptedLegislators,
    HistoricalPredecessors,
)
from domains.campaign_finance.ingest.federal_officeholder_loader import (
    OFFICE_US_HOUSE_DELEGATE,
    OFFICE_US_PRESIDENT,
    OFFICE_US_VICE_PRESIDENT,
    _OFFICE_US_HOUSE,
    _resolve_house_division,
    load_federal_house_officeholders,
    load_federal_senate_officeholders,
)
from domains.campaign_finance.ingest.fec_lookup import (
    resolve_federal_officeholder_fec_candidate_ids,
)
from domains.campaign_finance.ingest.officeholder_contact import (
    insert_officeholder_source_record,
    resolve_or_create_person_by_identifier,
    run_officeholder_row,
)
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source
from domains.civics.ingest import upsert_officeholding

LOGGER = logging.getLogger(__name__)


# Mapping from adapter executive-row type strings to canonical office UUIDs.
# Delegate is included here so the same pure helper resolves the third
# "non-chamber" bucket alongside president / vice_president.
OFFICE_BY_EXECUTIVE_TYPE: dict[str, UUID] = {
    "delegate": OFFICE_US_HOUSE_DELEGATE,
    "president": OFFICE_US_PRESIDENT,
    "vice_president": OFFICE_US_VICE_PRESIDENT,
}


@dataclass(frozen=True, slots=True)
class SpineConvergence:
    """All three parts of one person's identity convergence.

    ``candidates`` counts ``cf.candidate`` rows repointed at the spine person
    (the money side); ``candidacies`` counts ``civic.candidacy`` rows repointed
    or merged (the civic side); ``absorbed_persons`` counts FEC-only shadow
    ``core.person`` rows merged INTO the spine person and deleted (the identity
    side, civibus-5lm). They are returned together, rather than as independent
    calls, because repairing only one of them is exactly the class of defect
    this convergence path exists to close — see the helper docstrings.
    """

    candidates: int = 0
    candidacies: int = 0
    absorbed_persons: int = 0


@dataclass(slots=True)
class _BucketResult:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    converged_candidates: int = 0
    converged_candidacies: int = 0
    absorbed_persons: int = 0


@dataclass(slots=True)
class SpineLoadResult:
    """Per-bucket counters returned by :func:`load_federal_spine`."""

    house: _BucketResult = field(default_factory=_BucketResult)
    senate: _BucketResult = field(default_factory=_BucketResult)
    delegate: _BucketResult = field(default_factory=_BucketResult)
    president: _BucketResult = field(default_factory=_BucketResult)
    vice_president: _BucketResult = field(default_factory=_BucketResult)

    @property
    def inserted(self) -> int:
        return sum(bucket.inserted for bucket in self._buckets)

    @property
    def skipped(self) -> int:
        return sum(bucket.skipped for bucket in self._buckets)

    @property
    def quarantined(self) -> int:
        return 0

    @property
    def superseded(self) -> int:
        return 0

    @property
    def errors(self) -> int:
        return sum(bucket.errors for bucket in self._buckets)

    @property
    def converged_candidates(self) -> int:
        return sum(bucket.converged_candidates for bucket in self._buckets)

    @property
    def converged_candidacies(self) -> int:
        return sum(bucket.converged_candidacies for bucket in self._buckets)

    @property
    def absorbed_persons(self) -> int:
        return sum(bucket.absorbed_persons for bucket in self._buckets)

    @property
    def _buckets(self) -> tuple[_BucketResult, ...]:
        return (self.house, self.senate, self.delegate, self.president, self.vice_president)


# ---------------------------------------------------------------------------
# Data-source provenance for spine ingest
# ---------------------------------------------------------------------------

FEDERAL_SPINE_DATA_SOURCE_NAME = "US Congress Legislators (unitedstates/congress-legislators)"


def ensure_federal_spine_data_source(conn: psycopg.Connection) -> UUID:
    """Return the data_source id used for spine ingest provenance.

    Spine ingest records provenance against a dedicated DataSource so it is
    distinct from the per-chamber House Clerk / Senate XML directories owned by
    ``run_federal_officeholder_refresh``.
    """
    return ensure_data_source(
        conn,
        DataSource(
            domain="campaign_finance",
            jurisdiction="federal/congress",
            name=FEDERAL_SPINE_DATA_SOURCE_NAME,
            source_url="https://github.com/unitedstates/congress-legislators",
        ),
    )


# ---------------------------------------------------------------------------
# Convergence helper
# ---------------------------------------------------------------------------


def _converge_spine_candidacies(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    normalized_fec_ids: list[str],
) -> int:
    """Repoint ``civic.candidacy`` rows for these FEC candidate ids at the spine person.

    The civic sibling of the ``cf.candidate`` UPDATE below, and the reason it
    exists (civibus-5lm): ``federal-fec-masters`` runs *before*
    ``federal-congress-spine`` in the refresh plan and mints an FEC-only "shadow"
    ``core.person`` keyed on ``fec_candidate_id`` — the masters job even declares
    ``side_effects_repaired_by_job_key="federal-congress-spine"``. The races
    loader then binds ``civic.candidacy.person_id`` to that shadow. Convergence
    used to repair only the money side, so ``cf.candidate.person_id`` moved onto
    the bioguide-anchored spine person while the candidacy stayed behind.

    The user-visible consequence is severe, because the race page reads
    ``civic.candidacy.person_id`` for its ``/person/`` link: the incumbent's link
    pointed at a person row that has no money attached. Measured live on
    2026-08-19, Jon Ossoff's $77,279,766.48 sat on the spine row while the race
    page linked to the shadow. The blast radius is every chamber-switching
    incumbent — the highest-profile, highest-money races on the site.

    ``civic.candidacy.candidate_number`` carries the FEC ``CAND_ID`` the races
    loader copies from the source row (see ``ingest_candidate_civic_rows``), so
    it is the *same* key the ``cf.candidate`` UPDATE uses. That makes the match
    exact rather than heuristic: ``cf.candidate.fec_candidate_id`` is NOT NULL
    UNIQUE, and both sides are now keyed off one identifier.

    The move goes through ``repoint_candidacy_person``, the conflict-safe owner in
    ``core/entity_resolution/candidacy_merge.py`` — this deliberately does not
    open a second reconciliation path. ``uq_candidacy_canonical_key`` is
    ``(person_id, contest_id)``, so a naive UPDATE would raise whenever the spine
    person already holds a candidacy in the same contest. That helper instead
    COALESCEs the shadow row's fields into the canonical row and copies its
    ``core.entity_source`` provenance links across before dropping the redundant
    duplicate, so every surviving data point keeps its link to a source filing.

    Idempotent: on a re-run every matching candidacy already points at
    ``person_id`` and ``repoint_candidacy_person`` short-circuits to ``False``.

    Returns the number of candidacy rows moved or merged.
    """
    if not normalized_fec_ids:
        return 0

    with conn.cursor() as cur:
        # Read the work set up front. repoint_candidacy_person may DELETE the row
        # it was handed (the merge branch), so holding an open cursor over the
        # same rows while mutating them would be unsound.
        cur.execute(
            """
            SELECT id, person_id
            FROM civic.candidacy
            WHERE candidate_number = ANY(%s)
              AND person_id <> %s
            ORDER BY id
            """,
            (normalized_fec_ids, person_id),
        )
        misbound_candidacies: list[tuple[UUID, UUID]] = list(cur.fetchall())

    return sum(
        repoint_candidacy_person(
            conn,
            candidacy_id=candidacy_id,
            expected_person_id=current_person_id,
            target_person_id=person_id,
        )
        for candidacy_id, current_person_id in misbound_candidacies
    )


# Identifier keys an FEC-lane shadow person may carry. The cn/masters loaders
# mint persons with exactly {"fec_candidate_id": ...}; the spine adds
# 'fec_candidate_ids' when it merges. A person carrying ANY other key
# (bioguide_id, govtrack_id, wikidata_id, a future voter id, ...) has an
# independent identity anchor and is NEVER absorbed by this narrow path —
# collapsing two independently-anchored rows is entity resolution's job.
_FEC_SHADOW_IDENTIFIER_KEYS = frozenset({"fec_candidate_id", "fec_candidate_ids"})


def _shadow_fec_id_set(identifiers: dict[str, Any]) -> set[str]:
    """Every FEC candidate id a person row claims, scalar and array, trimmed."""
    fec_ids: set[str] = set()
    scalar = str(identifiers.get("fec_candidate_id") or "").strip()
    if scalar:
        fec_ids.add(scalar)
    for value in identifiers.get("fec_candidate_ids") or []:
        trimmed = str(value).strip()
        if trimmed:
            fec_ids.add(trimmed)
    return fec_ids


def _shadow_person_blockers(conn: psycopg.Connection, shadow_person_id: UUID) -> list[str]:
    """Name every condition that makes this row unsafe for the narrow absorb.

    Each blocker is a table the narrow path deliberately does not know how to
    merge without conflict machinery of its own:

    - ``officeholding``: uq_officeholding_canonical_key uses WITHOUT OVERLAPS;
      a blind repoint onto a spine person already holding the office for an
      overlapping period raises mid-refresh and aborts the whole spine load.
    - ``portrait``: idx_person_portrait_active_per_person allows one active
      portrait per person; moving a second one across would raise.
    - ``field_provenance``: idx_field_prov_current allows one current value per
      (person, field); merging needs a demote-the-loser policy.
    - ``contact_point`` and the ER bookkeeping tables (er_cluster_id,
      cluster_member, entity_cluster, match_decision, donor_cluster_person):
      each records identity facts about the row that a delete would orphan.

    A true FEC-lane shadow has NONE of these — nothing in the FEC candidate
    lane writes them — so in practice this returns []. When it does not, the
    absorb refuses that row and the refresh keeps going: two person rows remain
    (the pre-existing state, which the serving-side convergence above already
    keeps correct), and the general merge (tracked on civibus-5lm's follow-up)
    owns the conflict-aware handling.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                EXISTS (SELECT 1 FROM civic.officeholding
                        WHERE person_id = %(shadow)s) AS officeholding,
                EXISTS (SELECT 1 FROM core.person_portrait
                        WHERE person_id = %(shadow)s) AS portrait,
                EXISTS (SELECT 1 FROM core.field_provenance
                        WHERE entity_type = 'person' AND entity_id = %(shadow)s) AS field_provenance,
                EXISTS (SELECT 1 FROM core.contact_point
                        WHERE owner_type = 'person' AND owner_id = %(shadow)s) AS contact_point,
                EXISTS (SELECT 1 FROM core.person
                        WHERE id = %(shadow)s AND er_cluster_id IS NOT NULL) AS er_cluster,
                EXISTS (SELECT 1 FROM core.cluster_member
                        WHERE entity_type = 'person' AND entity_id = %(shadow)s) AS cluster_member,
                EXISTS (SELECT 1 FROM core.entity_cluster
                        WHERE entity_type = 'person' AND canonical_entity_id = %(shadow)s) AS entity_cluster,
                EXISTS (SELECT 1 FROM core.match_decision
                        WHERE entity_type = 'person'
                          AND (entity_id_a = %(shadow)s OR entity_id_b = %(shadow)s)) AS match_decision,
                EXISTS (SELECT 1 FROM core.donor_cluster_person
                        WHERE person_id = %(shadow)s) AS donor_cluster_person
            """,
            {"shadow": shadow_person_id},
        )
        row = cur.fetchone()
        blocker_names = (
            "officeholding",
            "portrait",
            "field_provenance",
            "contact_point",
            "er_cluster",
            "cluster_member",
            "entity_cluster",
            "match_decision",
            "donor_cluster_person",
        )
        return [name for name, present in zip(blocker_names, row) if present]


def _absorb_one_shadow_person(
    conn: psycopg.Connection,
    *,
    canonical_person_id: UUID,
    shadow_person_id: UUID,
    shadow_canonical_name: str,
    shadow_name_variants: list[str],
) -> None:
    """Move every reference off the shadow row onto the spine person, then delete it.

    The repoint inventory below is the complete set of tables referencing
    ``core.person`` (FKs: cf.candidate.person_id, cf.transaction.contributor_person_id,
    civic.candidacy.person_id, civic.officeholding.person_id,
    core.person_portrait.person_id, core.donor_cluster_person.person_id,
    prop.ownership.owner_person_id; polymorphic: core.entity_source,
    core.entity_address, core.field_provenance, core.contact_point, and the ER
    bookkeeping tables). Officeholding, portrait, field_provenance,
    contact_point and ER bookkeeping are eligibility blockers handled by
    ``_shadow_person_blockers`` — by the time this runs they are proven empty —
    so what remains is repointed here. The final DELETE doubles as the safety
    net: if this repo ever adds a person FK this function does not know about,
    the delete fails with a ForeignKeyViolation and aborts the refresh loudly
    instead of silently stranding rows.
    """
    # Candidacies go through repoint_candidacy_person, the existing
    # conflict-safe owner: uq_candidacy_canonical_key (person_id, contest_id)
    # means a plain UPDATE raises whenever the spine person already holds a
    # candidacy in the same contest; the helper merges field-wise and copies
    # core.entity_source provenance before dropping the duplicate row.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM civic.candidacy WHERE person_id = %s ORDER BY id",
            (shadow_person_id,),
        )
        shadow_candidacy_ids = [row[0] for row in cur.fetchall()]
    for candidacy_id in shadow_candidacy_ids:
        repoint_candidacy_person(
            conn,
            candidacy_id=candidacy_id,
            expected_person_id=shadow_person_id,
            target_person_id=canonical_person_id,
        )

    with conn.cursor() as cur:
        # Money rows: no unique constraint involves person_id, so plain UPDATEs
        # are conflict-free. The convergence UPDATE above already moved the rows
        # matching this person's FEC ids; these sweeps make the delete safe even
        # for rows attached to the shadow under some other id.
        cur.execute(
            "UPDATE cf.candidate SET person_id = %s WHERE person_id = %s",
            (canonical_person_id, shadow_person_id),
        )
        cur.execute(
            "UPDATE cf.transaction SET contributor_person_id = %s WHERE contributor_person_id = %s",
            (canonical_person_id, shadow_person_id),
        )
        # Parked property domain: kept in the inventory so un-parking never
        # discovers rows stranded on a deleted person.
        cur.execute(
            "UPDATE prop.ownership SET owner_person_id = %s WHERE owner_person_id = %s",
            (canonical_person_id, shadow_person_id),
        )

        # Address links carry UNIQUE (entity_type, entity_id, address_id,
        # address_role, valid_period WITHOUT OVERLAPS): move every link that
        # does not collide with one the spine person already has. What remains
        # after the UPDATE is by definition an overlap-duplicate of an existing
        # canonical link (same address, same role, overlapping period) — the
        # address FACT survives on the spine person, and the duplicate row's
        # source linkage survives through the entity_source move below, so the
        # DELETE loses nothing.
        cur.execute(
            """
            UPDATE core.entity_address AS shadow_link
            SET entity_id = %(canonical)s
            WHERE shadow_link.entity_type = 'person'
              AND shadow_link.entity_id = %(shadow)s
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_address AS canonical_link
                  WHERE canonical_link.entity_type = 'person'
                    AND canonical_link.entity_id = %(canonical)s
                    AND canonical_link.address_id = shadow_link.address_id
                    AND canonical_link.address_role = shadow_link.address_role
                    AND canonical_link.valid_period && shadow_link.valid_period
              )
            """,
            {"canonical": canonical_person_id, "shadow": shadow_person_id},
        )
        cur.execute(
            "DELETE FROM core.entity_address WHERE entity_type = 'person' AND entity_id = %s",
            (shadow_person_id,),
        )

        # Provenance links: copy-with-dedup then delete = move. Source records
        # themselves are never touched — every data point keeps its link to a
        # source filing, now through the surviving person.
        cur.execute(
            """
            INSERT INTO core.entity_source (
                entity_type, entity_id, source_record_id,
                extraction_role, confidence, extracted_fields
            )
            SELECT entity_type, %s, source_record_id,
                   extraction_role, confidence, extracted_fields
            FROM core.entity_source
            WHERE entity_type = 'person'
              AND entity_id = %s
            ON CONFLICT (entity_type, entity_id, source_record_id, extraction_role)
            DO NOTHING
            """,
            (canonical_person_id, shadow_person_id),
        )
        cur.execute(
            "DELETE FROM core.entity_source WHERE entity_type = 'person' AND entity_id = %s",
            (shadow_person_id,),
        )

        # The spine person's canonical_name always wins: it is the
        # human-formatted bioguide-anchored name ("Ossoff, Jon"), while the
        # shadow carries the raw FEC filing form ("OSSOFF, T. JONATHAN").
        # The FEC form is still an observed name for this human, so it is
        # preserved as a variant rather than discarded. No other scalar is
        # copied: FEC-lane shadows are minted with every biographical column
        # NULL, and the shadow's FEC ids are already on the spine person (the
        # eligibility subset check proved that before this ran).
        cur.execute(
            """
            UPDATE core.person
            SET name_variants = (
                    SELECT COALESCE(array_agg(DISTINCT observed_name ORDER BY observed_name), '{}')
                    FROM unnest(name_variants || %s::text[]) AS observed_name
                    WHERE BTRIM(COALESCE(observed_name, '')) <> ''
                      AND observed_name <> canonical_name
                ),
                updated_at = NOW()
            WHERE id = %s
            """,
            ([shadow_canonical_name, *shadow_name_variants], canonical_person_id),
        )

        # Everything that referenced the shadow now references the spine person,
        # so the duplicate row — the second search result, the orphan /person/
        # page — can finally go.
        cur.execute("DELETE FROM core.person WHERE id = %s", (shadow_person_id,))


def _absorb_fec_shadow_persons(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    normalized_fec_ids: list[str],
) -> int:
    """Merge FEC-only shadow person rows into the spine person and delete them.

    The identity side of convergence (civibus-5lm). ``federal-fec-masters`` runs
    before ``federal-congress-spine`` in the refresh plan and mints one
    ``core.person`` per unseen CAND_ID with identifiers ``{"fec_candidate_id"}``
    and no name columns. The two convergence steps above repoint everything such
    a row is POINTED AT BY — but the row itself survived, so /search returned
    two persons for one senator and the shadow's empty /person/ page stayed
    reachable (measured live 2026-08-19: "Ossoff, Jon" with $77,279,766.48 and
    "OSSOFF, T. JONATHAN" with nothing).

    Absorption is deliberately narrow. A row qualifies only when BOTH hold:

    1. its identifier keys are a subset of {fec_candidate_id, fec_candidate_ids}
       — no independent identity anchor; and
    2. every FEC id it claims is one the spine person already carries — the
       shadow makes no identity claim the spine row does not.

    plus none of the ``_shadow_person_blockers`` conditions. Anything else is
    logged and left alone: refusal preserves the previous (serving-side
    repaired) state, and the general merge belongs to entity resolution.

    Idempotent: absorbed rows are deleted, so a second run matches nothing.
    Returns the number of person rows absorbed.
    """
    if not normalized_fec_ids:
        return 0

    with conn.cursor() as cur:
        # Read the work set up front, mirroring _converge_spine_candidacies:
        # the absorb DELETEs person rows, so iterating an open cursor over the
        # same rows while mutating them would be unsound.
        cur.execute(
            """
            SELECT id, canonical_name, identifiers, name_variants
            FROM core.person
            WHERE id <> %(spine)s
              AND (
                    BTRIM(COALESCE(identifiers ->> 'fec_candidate_id', '')) = ANY(%(fec_ids)s)
                 OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            COALESCE(identifiers -> 'fec_candidate_ids', '[]'::jsonb)
                        ) AS claimed(fec_candidate_id)
                        WHERE BTRIM(claimed.fec_candidate_id) = ANY(%(fec_ids)s)
                    )
              )
            ORDER BY id
            """,
            {"spine": person_id, "fec_ids": normalized_fec_ids},
        )
        candidate_shadow_rows = list(cur.fetchall())

    spine_fec_ids = set(normalized_fec_ids)
    absorbed = 0
    for shadow_id, shadow_canonical_name, shadow_identifiers, shadow_name_variants in candidate_shadow_rows:
        extra_identifier_keys = set(shadow_identifiers) - _FEC_SHADOW_IDENTIFIER_KEYS
        if extra_identifier_keys:
            LOGGER.warning(
                "Not absorbing person %s into spine person %s: it carries independent "
                "identity anchors %s alongside a shared FEC candidate id; two anchored "
                "rows sharing an FEC id is an upstream data defect for entity resolution",
                shadow_id,
                person_id,
                sorted(extra_identifier_keys),
            )
            continue
        unshared_fec_ids = _shadow_fec_id_set(shadow_identifiers) - spine_fec_ids
        if unshared_fec_ids:
            LOGGER.warning(
                "Not absorbing person %s into spine person %s: it claims FEC candidate "
                "ids %s the spine person does not carry",
                shadow_id,
                person_id,
                sorted(unshared_fec_ids),
            )
            continue
        blockers = _shadow_person_blockers(conn, shadow_id)
        if blockers:
            LOGGER.warning(
                "Not absorbing FEC shadow person %s into spine person %s: it carries %s "
                "rows the narrow absorb does not merge; left for the general ER merge",
                shadow_id,
                person_id,
                ", ".join(blockers),
            )
            continue
        _absorb_one_shadow_person(
            conn,
            canonical_person_id=person_id,
            shadow_person_id=shadow_id,
            shadow_canonical_name=shadow_canonical_name,
            shadow_name_variants=list(shadow_name_variants or []),
        )
        absorbed += 1
    return absorbed


def _converge_spine_identity(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    fec_ids: list[str],
    bioguide_id: str | None = None,
    wikidata_id: str | None = None,
    govtrack_id: str | None = None,
) -> SpineConvergence:
    """Enrich identifiers on the spine person and repoint everything keyed to its FEC ids.

    Returns both convergence counts. The money side (``cf.candidate``) and the
    civic side (``civic.candidacy``) are repaired in one call on purpose: they are
    two halves of one identity claim, and repairing only the money side is the
    exact production defect civibus-5lm describes.

    The UPDATE is idempotent: when every matching candidate row already points
    at ``person_id``, no rows are touched. ``cf.candidate.updated_at`` is set by
    the existing ``trg_candidate_updated_at`` trigger so we do not set it here.
    """
    normalized_fec_ids = resolve_federal_officeholder_fec_candidate_ids(
        bioguide_id=bioguide_id,
        upstream_candidate_ids=fec_ids or [],
    )
    identifier_payload: dict[str, Any] = {}
    if normalized_fec_ids:
        identifier_payload["fec_candidate_id"] = normalized_fec_ids[0]
        identifier_payload["fec_candidate_ids"] = normalized_fec_ids
    if wikidata_id:
        identifier_payload["wikidata_id"] = wikidata_id
    if govtrack_id:
        identifier_payload["govtrack_id"] = govtrack_id
    if identifier_payload:
        merge_person_identifiers(conn, person_id=person_id, identifiers=identifier_payload)

    if not normalized_fec_ids:
        return SpineConvergence()

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cf.candidate
            SET person_id = %s
            WHERE fec_candidate_id = ANY(%s)
              AND (person_id IS NULL OR person_id <> %s)
            """,
            (person_id, normalized_fec_ids, person_id),
        )
        converged_candidates = cur.rowcount or 0

    # Order matters: candidacies move first (keyed by candidate_number, the
    # broadest sweep), then the absorb sweeps whatever still points at a shadow
    # row before deleting it. Running the absorb last means the shadow is
    # reference-free at DELETE time whenever the row is a true shadow.
    return SpineConvergence(
        candidates=converged_candidates,
        candidacies=_converge_spine_candidacies(
            conn,
            person_id=person_id,
            normalized_fec_ids=normalized_fec_ids,
        ),
        absorbed_persons=_absorb_fec_shadow_persons(
            conn,
            person_id=person_id,
            normalized_fec_ids=normalized_fec_ids,
        ),
    )


def _jsonable_raw_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip non-JSON-safe values (UUIDs, lists) from the row before persisting as raw_fields.

    ``compute_record_hash`` requires every value be a JSON-safe scalar. The
    adapter's delegate row carries ``office_id`` as a UUID (a convenience for
    downstream consumers); the spine loader does not consume that field —
    delegate office is the constant OFFICE_US_HOUSE_DELEGATE.
    """
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, list):
            safe[key] = ",".join(str(item) for item in value)
        else:
            safe[key] = value
    return safe


def _row_identity_lookup(
    conn: psycopg.Connection,
    *,
    bioguide_id: str,
    govtrack_id: str | None = None,
    wikidata_id: str | None = None,
) -> UUID | None:
    """Resolve the spine person from any identifier known to be present.

    Bioguide is the primary key for currently-serving members; only the VP-
    without-bioguide path needs the govtrack / wikidata fallbacks.
    """
    if bioguide_id:
        person_id = find_person_by_identifier(conn, "bioguide_id", bioguide_id)
        if person_id is not None:
            return person_id
    if govtrack_id:
        person_id = find_person_by_identifier(conn, "govtrack_id", govtrack_id)
        if person_id is not None:
            return person_id
    if wikidata_id:
        return find_person_by_identifier(conn, "wikidata_id", wikidata_id)
    return None


# ---------------------------------------------------------------------------
# Chamber paths — reuse existing loaders unchanged, then converge.
# ---------------------------------------------------------------------------


def _converge_chamber_rows(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    *,
    bucket: _BucketResult,
) -> None:
    """For each row that the chamber loaders just persisted, run convergence."""
    for row in rows:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if not bioguide_id:
            continue
        fec_ids = list(row.get("fec_ids") or [])
        person_id = _row_identity_lookup(
            conn,
            bioguide_id=bioguide_id,
            govtrack_id=row.get("govtrack_id"),
            wikidata_id=row.get("wikidata_id"),
        )
        if person_id is None:
            LOGGER.warning(
                "Skipping convergence for %s: spine person not found after chamber load",
                bioguide_id,
            )
            continue
        convergence = _converge_spine_identity(
            conn,
            person_id=person_id,
            fec_ids=fec_ids,
            bioguide_id=bioguide_id,
            wikidata_id=row.get("wikidata_id"),
            govtrack_id=row.get("govtrack_id"),
        )
        bucket.converged_candidates += convergence.candidates
        bucket.converged_candidacies += convergence.candidacies
        bucket.absorbed_persons += convergence.absorbed_persons


def _record_chamber_bucket(result: LoadResult, bucket: _BucketResult) -> None:
    bucket.inserted += result.inserted
    bucket.skipped += result.skipped
    bucket.errors += result.errors


# ---------------------------------------------------------------------------
# Delegate / executive paths — small, mirror the chamber loader idioms.
# ---------------------------------------------------------------------------


def _load_delegate_row(
    conn: psycopg.Connection,
    row: dict[str, Any],
    *,
    data_source_id: UUID,
    bucket: _BucketResult,
) -> None:
    """Insert one delegate as person + congressional-district officeholding."""

    def _process_row() -> None:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if not bioguide_id:
            # Without a bioguide we cannot anchor identity; skip.
            bucket.skipped += 1
            return
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        state = (row.get("state") or "").strip()
        district = (row.get("district") or "").strip()

        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"delegate:{bioguide_id}",
            raw_row=_jsonable_raw_row(row),
        )
        row_inserted = source_record_id is not None
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key="bioguide_id",
            identifier_value=bioguide_id,
            first_name=first_name,
            last_name=last_name,
            source_record_id=source_record_id,
        )
        division_id = _resolve_house_division(conn, state, district) if state and district else None
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE_DELEGATE,
                electoral_division_id=division_id,
                holder_status="elected",
                valid_period=ValidDateRange(),
                date_precision="year",
                source_record_id=source_record_id,
            ),
        )

        fec_ids = list(row.get("fec_ids") or [])
        if fec_ids:
            convergence = _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=fec_ids,
                bioguide_id=bioguide_id,
                wikidata_id=row.get("wikidata_id"),
                govtrack_id=row.get("govtrack_id"),
            )
            bucket.converged_candidates += convergence.candidates
            bucket.converged_candidacies += convergence.candidacies
            bucket.absorbed_persons += convergence.absorbed_persons

        if row_inserted:
            bucket.inserted += 1
        else:
            bucket.skipped += 1

    if not run_officeholder_row(
        conn,
        logger=LOGGER,
        failure_message="Error ingesting federal delegate row: %s",
        raw_row=row,
        operation=_process_row,
    ):
        bucket.errors += 1


def _load_executive_row(
    conn: psycopg.Connection,
    row: dict[str, Any],
    *,
    office_type: str,
    data_source_id: UUID,
    bucket: _BucketResult,
) -> None:
    """Insert one executive (president or vp) as person + nationwide officeholding."""
    office_id = OFFICE_BY_EXECUTIVE_TYPE[office_type]
    source_record_key_prefix = "president" if office_type == "president" else "vp"

    def _process_row() -> None:
        bioguide_id = (row.get("bioguide_id") or "").strip()
        govtrack_id = (row.get("govtrack_id") or "").strip() or None
        wikidata_id = (row.get("wikidata_id") or "").strip() or None
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()

        # Identity anchor: bioguide preferred; for the VP-without-bioguide
        # path, fall back to govtrack_id then wikidata_id.
        identifier_key: str
        identifier_value: str
        if bioguide_id:
            identifier_key = "bioguide_id"
            identifier_value = bioguide_id
        elif govtrack_id:
            identifier_key = "govtrack_id"
            identifier_value = govtrack_id
        elif wikidata_id:
            identifier_key = "wikidata_id"
            identifier_value = wikidata_id
        else:
            bucket.skipped += 1
            return

        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"{source_record_key_prefix}:{identifier_value}",
            raw_row=_jsonable_raw_row(row),
        )
        row_inserted = source_record_id is not None
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key=identifier_key,
            identifier_value=identifier_value,
            first_name=first_name,
            last_name=last_name,
            source_record_id=source_record_id,
        )
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=office_id,
                electoral_division_id=None,
                holder_status="elected",
                valid_period=ValidDateRange(),
                date_precision="year",
                source_record_id=source_record_id,
            ),
        )

        fec_ids = list(row.get("fec_ids") or [])
        if fec_ids or wikidata_id or govtrack_id:
            convergence = _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=fec_ids,
                bioguide_id=bioguide_id,
                wikidata_id=wikidata_id,
                govtrack_id=govtrack_id,
            )
            bucket.converged_candidates += convergence.candidates
            bucket.converged_candidacies += convergence.candidacies
            bucket.absorbed_persons += convergence.absorbed_persons

        if row_inserted:
            bucket.inserted += 1
        else:
            bucket.skipped += 1

    if not run_officeholder_row(
        conn,
        logger=LOGGER,
        failure_message=f"Error ingesting federal {office_type} row: %s",
        raw_row=row,
        operation=_process_row,
    ):
        bucket.errors += 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_federal_spine(
    conn: psycopg.Connection,
    adapted: AdaptedLegislators,
    *,
    data_source_id: UUID,
) -> SpineLoadResult:
    """Materialize the federal officeholder spine and converge cf.candidate money.

    Parameters
    ----------
    conn:
        Open psycopg connection. The caller controls commit boundaries; this
        function does not commit on its own.
    adapted:
        Bucketed rows from :func:`adapt_legislators_yaml`.
    data_source_id:
        Provenance handle returned by :func:`ensure_federal_spine_data_source`.
    """
    result = SpineLoadResult()

    house_result = load_federal_house_officeholders(conn, adapted.house_rows, data_source_id=data_source_id)
    _record_chamber_bucket(house_result, result.house)
    _converge_chamber_rows(conn, adapted.house_rows, bucket=result.house)

    senate_result = load_federal_senate_officeholders(conn, adapted.senate_rows, data_source_id=data_source_id)
    _record_chamber_bucket(senate_result, result.senate)
    _converge_chamber_rows(conn, adapted.senate_rows, bucket=result.senate)

    for delegate_row in adapted.delegate_rows:
        _load_delegate_row(
            conn,
            delegate_row,
            data_source_id=data_source_id,
            bucket=result.delegate,
        )

    for president_row in adapted.president_rows:
        _load_executive_row(
            conn,
            president_row,
            office_type="president",
            data_source_id=data_source_id,
            bucket=result.president,
        )

    for vp_row in adapted.vp_rows:
        _load_executive_row(
            conn,
            vp_row,
            office_type="vice_president",
            data_source_id=data_source_id,
            bucket=result.vice_president,
        )

    return result


def load_vacancy_predecessors(
    conn: psycopg.Connection,
    predecessors: HistoricalPredecessors,
    *,
    data_source_id: UUID,
) -> int:
    """Create closed officeholding records for vacant House seats.

    Returns the number of predecessor officeholdings upserted.
    """
    count = 0
    for pred in predecessors.house_predecessors:
        if not pred.bioguide_id:
            continue
        source_record_id = insert_officeholder_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"vacancy-predecessor:{pred.bioguide_id}",
            raw_row={
                "bioguide_id": pred.bioguide_id,
                "first_name": pred.first_name,
                "last_name": pred.last_name,
                "state": pred.state,
                "district": pred.district,
                "party": pred.party,
                "term_end": pred.term_end,
            },
        )
        person_id = resolve_or_create_person_by_identifier(
            conn,
            identifier_key="bioguide_id",
            identifier_value=pred.bioguide_id,
            first_name=pred.first_name,
            last_name=pred.last_name,
            source_record_id=source_record_id,
        )
        division_id = _resolve_house_division(conn, pred.state, pred.district)
        end_date = date.fromisoformat(pred.term_end)
        upsert_officeholding(
            conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_US_HOUSE,
                electoral_division_id=division_id,
                holder_status="former",
                valid_period=ValidDateRange(end_date=end_date),
                date_precision="day",
                source_record_id=source_record_id,
            ),
        )
        if pred.fec_ids:
            _converge_spine_identity(
                conn,
                person_id=person_id,
                fec_ids=pred.fec_ids,
                wikidata_id=pred.wikidata_id or None,
                govtrack_id=pred.govtrack_id or None,
            )
        count += 1
        LOGGER.info(
            "Vacancy predecessor: %s %s (%s-%s), term ended %s",
            pred.first_name,
            pred.last_name,
            pred.state,
            pred.district,
            pred.term_end,
        )
    return count


__all__ = [
    "FEDERAL_SPINE_DATA_SOURCE_NAME",
    "OFFICE_BY_EXECUTIVE_TYPE",
    "SpineLoadResult",
    "_BucketResult",
    "ensure_federal_spine_data_source",
    "load_federal_spine",
    "load_vacancy_predecessors",
]
