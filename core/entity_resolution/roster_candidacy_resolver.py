
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.extract import extract_rows_for_matching
from core.entity_resolution.scoring import run_deterministic_rules, score_rows
from domains.civics.ingest import repoint_candidacy_person


@dataclass(frozen=True, slots=True)
class _ResolverCandidateRow:
    roster_person_id: UUID
    candidacy_person_id: UUID
    candidacy_id: UUID


@dataclass(frozen=True, slots=True)
class _PairDecision:
    decision: str
    confidence: float


def _canonical_pair(person_id_a: UUID, person_id_b: UUID) -> tuple[UUID, UUID]:
    if person_id_a < person_id_b:
        return person_id_a, person_id_b
    return person_id_b, person_id_a


def _select_candidate_rows(conn: psycopg.Connection) -> tuple[list[_ResolverCandidateRow], int]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                oh.person_id AS roster_person_id,
                cd.person_id AS candidacy_person_id,
                cd.id AS candidacy_id
            FROM civic.officeholding oh
            JOIN core.source_record sr
              ON sr.id = oh.source_record_id
            JOIN civic.contest ct
              ON ct.office_id = oh.office_id
             AND ct.electoral_division_id IS NOT DISTINCT FROM oh.electoral_division_id
            JOIN civic.candidacy cd
              ON cd.contest_id = ct.id
            WHERE sr.source_record_key LIKE 'official_roster:%:snapshot'
              AND (
                    oh.valid_period IS NULL
                    OR ct.election_date IS NULL
                    OR oh.valid_period @> ct.election_date
                  )
            """
        )
        rows = cursor.fetchall()

    already_linked_rows = 0
    unresolved_rows: list[_ResolverCandidateRow] = []
    for row in rows:
        roster_person_id = row["roster_person_id"]
        candidacy_person_id = row["candidacy_person_id"]
        if roster_person_id == candidacy_person_id:
            already_linked_rows += 1
            continue
        unresolved_rows.append(
            _ResolverCandidateRow(
                roster_person_id=roster_person_id,
                candidacy_person_id=candidacy_person_id,
                candidacy_id=row["candidacy_id"],
            )
        )

    return unresolved_rows, already_linked_rows


def _deterministic_pair_scores_for_candidate_ids(
    conn: psycopg.Connection,
    *,
    candidate_person_ids: set[UUID],
) -> list[dict[str, Any]]:
    deterministic_pairs = run_deterministic_rules(conn, "person")
    return [
        pair
        for pair in deterministic_pairs
        if pair["entity_id_a"] in candidate_person_ids and pair["entity_id_b"] in candidate_person_ids
    ]


def _score_candidate_pairs(
    conn: psycopg.Connection,
    *,
    candidate_person_ids: set[UUID],
    auto_merge_threshold: float | None,
) -> dict[tuple[UUID, UUID], _PairDecision]:
    """Score candidate rows, falling back to deterministic-only matches when Splink is unavailable."""
    if len(candidate_person_ids) < 2:
        return {}

    extracted_rows = extract_rows_for_matching(conn, "person")
    candidate_rows = [row for row in extracted_rows if row["id"] in candidate_person_ids]
    if len(candidate_rows) < 2:
        return {}

    deterministic_pairs = _deterministic_pair_scores_for_candidate_ids(
        conn,
        candidate_person_ids=candidate_person_ids,
    )
    try:
        scored_pairs = score_rows(
            candidate_rows,
            "person",
            deterministic_pairs=deterministic_pairs,
        )
    except RuntimeError as exc:
        if "Splink settings are unavailable" not in str(exc):
            raise
        # Roster/candidacy repair should still apply exact deterministic matches
        # even in lightweight environments that omit the probabilistic runtime.
        scored_pairs = deterministic_pairs
    if not scored_pairs:
        return {}

    classified_pairs = classify_scored_pairs(
        scored_pairs,
        auto_merge_threshold=auto_merge_threshold,
    )
    decisions_by_pair: dict[tuple[UUID, UUID], _PairDecision] = {}
    for pair in classified_pairs:
        decisions_by_pair[_canonical_pair(pair["entity_id_a"], pair["entity_id_b"])] = _PairDecision(
            decision=pair["decision"],
            confidence=float(pair["confidence"]),
        )
    return decisions_by_pair


def resolve_roster_candidacy_people(
    conn: psycopg.Connection,
    *,
    auto_merge_threshold: float | None = None,
) -> dict[str, int]:
    """Link unresolved roster/candidacy people through the shared ER scoring path."""
    unresolved_rows, already_linked_rows = _select_candidate_rows(conn)
    total_candidate_rows = len(unresolved_rows) + already_linked_rows

    rows_by_pair: dict[tuple[UUID, UUID], list[_ResolverCandidateRow]] = {}
    candidate_person_ids: set[UUID] = set()
    for row in unresolved_rows:
        pair_key = _canonical_pair(row.roster_person_id, row.candidacy_person_id)
        rows_by_pair.setdefault(pair_key, []).append(row)
        candidate_person_ids.add(row.roster_person_id)
        candidate_person_ids.add(row.candidacy_person_id)

    decisions_by_pair = _score_candidate_pairs(
        conn,
        candidate_person_ids=candidate_person_ids,
        auto_merge_threshold=auto_merge_threshold,
    )

    mutated_rows = 0
    skipped_rows = 0
    matched_rows_by_candidacy: dict[UUID, list[tuple[_ResolverCandidateRow, float]]] = {}
    for pair_key, rows_for_pair in rows_by_pair.items():
        pair_decision = decisions_by_pair.get(pair_key)
        if pair_decision is None or pair_decision.decision != "match":
            skipped_rows += len(rows_for_pair)
            continue

        for row in rows_for_pair:
            matched_rows_by_candidacy.setdefault(row.candidacy_id, []).append((row, pair_decision.confidence))

    for matched_rows in matched_rows_by_candidacy.values():
        distinct_roster_person_ids = {row.roster_person_id for row, _ in matched_rows}
        if len(distinct_roster_person_ids) != 1:
            skipped_rows += len(matched_rows)
            continue

        best_row, _ = max(
            matched_rows,
            key=lambda item: (
                item[1],
                str(item[0].roster_person_id),
                str(item[0].candidacy_person_id),
                str(item[0].candidacy_id),
            ),
        )
        if repoint_candidacy_person(
            conn,
            candidacy_id=best_row.candidacy_id,
            expected_person_id=best_row.candidacy_person_id,
            target_person_id=best_row.roster_person_id,
        ):
            mutated_rows += 1
            skipped_rows += len(matched_rows) - 1
        else:
            skipped_rows += len(matched_rows)

    return {
        "candidate_pairs": total_candidate_rows,
        "linked_rows": already_linked_rows + mutated_rows,
        "skipped_rows": skipped_rows,
        "already_linked_rows": already_linked_rows,
        "mutated_rows": mutated_rows,
    }
