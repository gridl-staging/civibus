"""GA bounded-commit specimen: the relational pass commits each completed batch mid-loop.

Lives beside ``test_load.py`` rather than inside it because that file already sits at the
800-line hard limit; this is a distinct, DB-heavy concern with its own bulk fixture.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    bulk_fixture_entity_row_counts,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper import load as ga_load_module
from domains.campaign_finance.jurisdictions.states.GA.scraper.load import (
    load_ga_contributions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.load_test_support import (
    write_ga_contribution_fixture,
)

pytestmark = pytest.mark.integration

# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from
# `ga_load_module._COMMIT_BATCH_ROWS`. The falsifiability probe for this specimen
# monkeypatches that module constant above the fixture size; an expectation derived from
# the live constant would move with the probe and the specimen could never go red.
_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_GA_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# The fixture gives every row a distinct donor but one shared street and one shared
# committee, so a completed provenance pass writes exactly this footprint.
_GA_LOADED_ADDRESS_ROWS = 1
_GA_LOADED_COMMITTEE_ROWS = 1


def test_ga_with_filings_resolves_parser_and_provenance_loader_as_one_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    parsed_rows = [{"row": "paired"}]
    provenance_result = ga_load_module.LoadResult(inserted=1, skipped=0, errors=0, elapsed_seconds=0.0)
    provenance_loader = MagicMock(return_value=provenance_result)
    relational_loader = MagicMock()

    monkeypatch.setattr(ga_load_module, "parse_contributions", MagicMock(return_value=parsed_rows))
    monkeypatch.setattr(ga_load_module, "load_ga_contributions", provenance_loader)
    monkeypatch.setattr(ga_load_module, "ensure_ga_data_source", MagicMock(return_value="data-source-id"))
    monkeypatch.setattr(ga_load_module, "commit_managed_transaction", MagicMock())
    monkeypatch.setattr(ga_load_module, "_load_ga_relational_transactions", relational_loader)

    result = ga_load_module.load_ga_contributions_with_filings(conn, Path("contributions.csv"))

    assert result is provenance_result
    provenance_loader.assert_called_once_with(conn, parsed_rows, limit=None)
    relational_loader.assert_called_once_with(
        conn,
        parsed_rows,
        data_source_id="data-source-id",
        data_type="contributions",
        limit=None,
    )


def test_load_ga_with_filings_commits_relational_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 relational rows leaves exactly those 1,000 durable.

    Before Stage 4 the relational pass committed once, at the end of the job, so this
    interruption discarded every linked row and an independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = write_ga_contribution_fixture(tmp_path, row_count=_GA_BULK_ROW_COUNT)
        seed_bulk_fixture(resources, db_conn, fixture, expected_unique_source_record_keys=_GA_BULK_ROW_COUNT)
        write_counts = install_write_interrupt(
            monkeypatch,
            ga_load_module,
            "_upsert_ga_transaction_with_filing",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_ga_contributions_with_filings(db_conn, fixture.contributions_path)
        db_conn.rollback()

        # The provenance pass ran to completion and flushed all of its rows; the relational
        # pass was interrupted on row 1,001, so exactly its first full batch is durable.
        assert write_counts["writes"] == _GA_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _GA_BULK_ROW_COUNT
        assert transaction_count == _EXPECTED_DURABLE_BATCH_ROWS

        # The completed provenance pass also created the donor, address, and committee
        # rows behind those transactions. The stack's cleanup deletes them and then
        # re-reads this same count, so a cleanup that stops covering them — and quietly
        # grows the shared database on every run — fails this specimen.
        assert bulk_fixture_entity_row_counts(fixture) == {
            "person": _GA_BULK_ROW_COUNT,
            "organization": _GA_LOADED_COMMITTEE_ROWS,
            "address": _GA_LOADED_ADDRESS_ROWS,
            "committee": _GA_LOADED_COMMITTEE_ROWS,
        }
