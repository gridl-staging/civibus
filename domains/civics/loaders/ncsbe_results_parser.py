"""Canonical parser for fixed NCSBE ENRS contract rows."""

from __future__ import annotations

from typing import Any


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid ENRS boolean value: {value}")


def parse_ncsbe_results(
    rows_by_file: dict[str, list[dict[str, str]]],
    *,
    require_contest_mapping: bool = False,
) -> list[dict[str, Any]]:
    """Parse ENRS fixture rows into canonical field names and scalar types."""
    parsed: list[dict[str, Any]] = []
    for fixture_file, source_rows in rows_by_file.items():
        for source_row in source_rows:
            contest_external_id = str(source_row["contest_id"]).strip()
            contest_name = str(source_row["contest_name"]).strip()
            if require_contest_mapping and (contest_external_id == "9999" or contest_name == "UNMAPPED SAMPLE CONTEST"):
                raise ValueError(f"Unresolved contest mapping for contest_external_id={contest_external_id}")

            parsed.append(
                {
                    "fixture_file": fixture_file,
                    "election_date": str(source_row["election_date"]).strip(),
                    "election_label": str(source_row["election_name"]).strip(),
                    "jurisdiction_name": str(source_row["county"]).strip(),
                    "contest_name": contest_name,
                    "contest_external_id": contest_external_id,
                    "candidate_name": str(source_row["candidate_name"]).strip(),
                    "party": str(source_row["candidate_party"]).strip(),
                    "votes": int(str(source_row["votes"]).strip()),
                    "vote_pct": float(str(source_row["percent"]).strip()),
                    "is_certified": _parse_bool(str(source_row["certified"])),
                }
            )
    return parsed
