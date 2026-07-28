"""Test-only query instrumentation for the NCSBE candidate-listing loader."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


QUERY_FAMILIES = (
    "data_source_write",
    "data_source_lookup",
    "source_record_lookup",
    "source_record_lock",
    "source_record_write",
    "entity_source_write",
    "office_lookup",
    "office_write",
    "electoral_division_lookup",
    "electoral_division_write",
    "contest_lookup",
    "contest_write",
    "person_lookup",
    "person_write",
    "state_senate_legacy_reconciliation",
    "candidacy_lookup",
    "candidacy_write",
    "schema_lookup",
    "unknown",
)


@dataclass(frozen=True)
class CandidateListingQueryProbeResult:
    rows: int
    elapsed_seconds: float
    families: Counter[str]

    @property
    def total_queries(self) -> int:
        return sum(self.families.values())

    @property
    def rows_per_second(self) -> float:
        return self.rows / self.elapsed_seconds

    def projected_seconds(self, *, row_count: int) -> float:
        return self.elapsed_seconds * row_count / self.rows


class CountingConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self.families: Counter[str] = Counter({family: 0 for family in QUERY_FAMILIES})

    def execute(self, query: object, params: object | None = None, *args: object, **kwargs: object) -> Any:
        self._record(query)
        if params is None:
            return self._connection.execute(query, *args, **kwargs)
        return self._connection.execute(query, params, *args, **kwargs)

    def cursor(self, *args: object, **kwargs: object) -> "CountingCursor":
        return CountingCursor(self._connection.cursor(*args, **kwargs), self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def _record(self, query: object) -> None:
        as_string = getattr(query, "as_string", None)
        rendered_query = as_string(self._connection) if callable(as_string) else str(query)
        self.families[_classify_sql(rendered_query)] += 1


class CountingCursor:
    def __init__(self, cursor: Any, connection: CountingConnection) -> None:
        self._cursor = cursor
        self._connection = connection

    def execute(self, query: object, params: object | None = None, *args: object, **kwargs: object) -> Any:
        self._connection._record(query)
        if params is None:
            return self._cursor.execute(query, *args, **kwargs)
        return self._cursor.execute(query, params, *args, **kwargs)

    def __enter__(self) -> "CountingCursor":
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._cursor.__exit__(*args)

    def __iter__(self) -> Any:
        return iter(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


def write_candidate_listing_prefix(source_path: Path, output_path: Path, *, row_limit: int) -> Path:
    with source_path.open("r", encoding="utf-8", newline="") as source_file:
        reader = csv.DictReader(source_file)
        assert reader.fieldnames is not None
        rows = [row for index, row in enumerate(reader) if index < row_limit]

    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def measure_candidate_listing_queries(
    connection: Any,
    *,
    csv_path: Path,
    today: object,
    load_candidate_listing: Any,
) -> CandidateListingQueryProbeResult:
    counting_connection = CountingConnection(connection)
    started_at = time.perf_counter()
    summary = load_candidate_listing(counting_connection, csv_path=csv_path, today=today)
    elapsed_seconds = time.perf_counter() - started_at
    assert summary.rows_loaded > 0
    return CandidateListingQueryProbeResult(
        rows=summary.rows_loaded,
        elapsed_seconds=elapsed_seconds,
        families=counting_connection.families,
    )


def _classify_sql(sql: str) -> str:
    normalized = " ".join(sql.lower().replace('"', "").split())
    if "insert into core.data_source" in normalized:
        return "data_source_write"
    if "from core.data_source" in normalized:
        return "data_source_lookup"
    if "pg_advisory_xact_lock" in normalized:
        return "source_record_lock"
    if "from core.source_record" in normalized or "select id from core.source_record" in normalized:
        return "source_record_lookup"
    if "insert into core.source_record" in normalized:
        return "source_record_write"
    if (
        "insert into core.entity_source" in normalized
        or "from core.entity_source" in normalized
        or "join core.entity_source" in normalized
    ):
        return "entity_source_write"
    if "from civic.office" in normalized:
        return "office_lookup"
    if "insert into civic.office" in normalized or "update civic.office" in normalized:
        return "office_write"
    if "from civic.electoral_division" in normalized:
        return "electoral_division_lookup"
    if "insert into civic.electoral_division" in normalized or "update civic.electoral_division" in normalized:
        return "electoral_division_write"
    if "delete from civic.candidacy legacy" in normalized:
        return "state_senate_legacy_reconciliation"
    if "update civic.candidacy" in normalized or "delete from civic.contest" in normalized:
        return "state_senate_legacy_reconciliation"
    if "update civic.contest set electoral_division_id" in normalized:
        return "state_senate_legacy_reconciliation"
    if "from civic.contest ct join civic.electoral_division" in normalized:
        return "state_senate_legacy_reconciliation"
    if "insert into civic.contest" in normalized or "update civic.contest" in normalized:
        return "contest_write"
    if "from civic.contest" in normalized or "select ct.id from civic.contest" in normalized:
        return "contest_lookup"
    if "from core.person" in normalized or "join core.person" in normalized:
        return "person_lookup"
    if "insert into core.person" in normalized:
        return "person_write"
    if "from civic.candidacy" in normalized:
        return "candidacy_lookup"
    if "insert into civic.candidacy" in normalized or "update civic.candidacy" in normalized:
        return "candidacy_write"
    if "from information_schema.columns" in normalized:
        return "schema_lookup"
    return "unknown"


def _candidate_listing_counts(connection: Any) -> dict[str, int]:
    candidate_listing_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM civic.candidacy AS candidacy
        JOIN core.source_record AS source_record
          ON source_record.id = candidacy.source_record_id
        JOIN core.data_source AS data_source
          ON data_source.id = source_record.data_source_id
        WHERE data_source.name = 'ncsbe_candidate_listing_2026'
        """
    ).fetchone()[0]
    source_records = connection.execute(
        """
        SELECT COUNT(*)
        FROM core.source_record AS source_record
        JOIN core.data_source AS data_source
          ON data_source.id = source_record.data_source_id
        WHERE data_source.name = 'ncsbe_candidate_listing_2026'
        """
    ).fetchone()[0]
    return {
        "candidate_listing_candidacies": candidate_listing_rows,
        "candidate_listing_source_records": source_records,
    }


def capture_rollback_isolation_counts(connection: Any) -> dict[str, dict[str, int]]:
    """Capture measured rows, roll back, and prove that the transaction left no residue."""
    measured_transaction_counts = _candidate_listing_counts(connection)
    connection.rollback()
    post_rollback_counts = _candidate_listing_counts(connection)
    connection.rollback()
    return {
        "measured_transaction_counts": measured_transaction_counts,
        "post_rollback_counts": post_rollback_counts,
    }


def _result_payload(result: CandidateListingQueryProbeResult) -> dict[str, object]:
    return {
        "rows": result.rows,
        "elapsed_seconds": result.elapsed_seconds,
        "rows_per_second": result.rows_per_second,
        "total_statements": result.total_queries,
        "statements_per_row": result.total_queries / result.rows,
        "projected_7152_seconds": result.projected_seconds(row_count=7_152),
        "families": dict(result.families),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure one rollback-isolated candidate-listing rung")
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--rows", required=True, type=int)
    parser.add_argument("--today", default="2026-11-03", type=date.fromisoformat)
    args = parser.parse_args()

    from core.db import get_connection
    from domains.civics.loaders.ncsbe_candidate_listing import load_candidate_listing

    connection = get_connection()
    try:
        with tempfile.TemporaryDirectory(prefix="candidate-listing-query-probe-") as temp_dir:
            prefix_path = write_candidate_listing_prefix(
                args.fixture,
                Path(temp_dir) / "candidate_listing_prefix.csv",
                row_limit=args.rows,
            )
            first = measure_candidate_listing_queries(
                connection,
                csv_path=prefix_path,
                today=args.today,
                load_candidate_listing=load_candidate_listing,
            )
            rerun = measure_candidate_listing_queries(
                connection,
                csv_path=prefix_path,
                today=args.today,
                load_candidate_listing=load_candidate_listing,
            )
            isolation_counts = capture_rollback_isolation_counts(connection)
        print(
            json.dumps(
                {
                    "first": _result_payload(first),
                    "rerun": _result_payload(rerun),
                    "two_load_projected_7152_seconds": first.projected_seconds(row_count=7_152)
                    + rerun.projected_seconds(row_count=7_152),
                    **isolation_counts,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
