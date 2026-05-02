from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper.cli_test_support import (
    create_minimal_registry,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    TransactionSearchCriteria,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    NCTransactionsLoadResult,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest import (
    orchestrate_committee_ingest,
)

pytestmark = pytest.mark.integration

_WINDOW_START = date(2025, 1, 1)
_WINDOW_END = date(2025, 1, 31)


def _load_result() -> LoadResult:
    return LoadResult(
        inserted=1,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )


def _load_result_with_filtered(filtered: int) -> NCTransactionsLoadResult:
    return NCTransactionsLoadResult(
        inserted=1,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
        year_filtered=filtered,
    )


def _status_rows(db_conn: psycopg.Connection) -> list[tuple[str, str, int, str | None]]:
    rows = db_conn.execute(
        """
        SELECT sboe_id, status, attempt_count, last_error
        FROM cf.nc_orchestrator_progress
        ORDER BY sboe_id ASC
        """
    ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def test_orchestrator_tolerates_isolated_retryable_failures_then_breaks_on_streak(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One retryable failure mid-run must NOT abort the unbounded crawl;
    the orchestrator must continue with the next committee. A streak of
    consecutive retryable failures (default 3) DOES break the run, since
    that signals systemic portal trouble.

    Why: the 2026-04-26 unbounded prod run aborted at 29/3,668 committees
    completed because a single Playwright timeout on the 30th committee
    triggered the prior break-on-first-retryable behavior. Tolerating
    isolated failures is what makes the unbounded crawl actually unbounded.
    """
    rows = [
        {
            "sboe_id": f"STA-S-{i:03d}",
            "committee_name": f"Committee {i}",
            "org_group_id": 100 + i,
            "last_filing_date": None,
            "is_active": True,
        }
        for i in range(1, 4)
    ]
    create_minimal_registry(db_conn, rows)

    # Sequence: 1st committee success, 2nd retry (counter -> 1, NOT >= 3), 3rd
    # success (counter resets). 3 committees total, no streak hits the budget,
    # all 3 are claimed once and the loop exits when the queue empties.
    # Committees claimed in sboe_id ASC order: STA-S-001, STA-S-002, STA-S-003.
    side_effects: list[Exception | None] = [
        None,  # STA-S-001 success
        RuntimeError("portal timeout"),  # STA-S-002 retry, counter=1
        None,  # STA-S-003 success (counter resets)
        None,  # STA-S-002 re-claim (was pending) success
    ]
    transaction_download = MagicMock(side_effect=side_effects)

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        consecutive_retryable_budget=3,
    )

    # No streak of 3 consecutive retries occurred, so the loop runs until
    # the orchestrator progress queue empties. Final outcome: every committee
    # ends in `completed` (the retry-once-then-succeed path is exactly the
    # tolerance the unbounded crawl needs).
    assert result.retryable_failures == 1
    assert result.completed == 3, (
        f"every committee should ultimately complete; got completed={result.completed}, "
        f"retryable={result.retryable_failures}"
    )
    statuses = db_conn.execute("SELECT status FROM cf.nc_orchestrator_progress ORDER BY sboe_id").fetchall()
    assert all(row[0] == "completed" for row in statuses)


def test_orchestrator_seeds_and_runs_only_allowlisted_committees(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-A-003",
                "committee_name": "Committee 3",
                "last_filing_date": date(2025, 1, 3),
                "is_active": True,
            },
            {
                "sboe_id": "STA-A-001",
                "committee_name": "Committee 1",
                "last_filing_date": date(2025, 1, 3),
                "is_active": True,
            },
            {
                "sboe_id": "STA-A-002",
                "committee_name": "Committee 2",
                "last_filing_date": date(2025, 1, 3),
                "is_active": True,
            },
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        allowlist_sboe_ids=["STA-A-003", "STA-A-001"],
    )

    assert result.seeded == 2
    assert result.claimed == 2
    assert result.completed == 2

    statuses = db_conn.execute(
        """
        SELECT sboe_id, status
        FROM cf.nc_orchestrator_progress
        ORDER BY sboe_id ASC
        """
    ).fetchall()
    assert statuses == [("STA-A-001", "completed"), ("STA-A-003", "completed")]


def test_orchestrator_allowlisted_rerun_does_not_reclaim_or_claim_out_of_scope_queue_rows(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-R-001",
                "committee_name": "Committee 1",
                "org_group_id": 1001,
                "last_filing_date": None,
                "is_active": True,
            },
            {
                "sboe_id": "STA-R-002",
                "committee_name": "Committee 2",
                "org_group_id": 1002,
                "last_filing_date": None,
                "is_active": True,
            },
            {
                "sboe_id": "STA-R-003",
                "committee_name": "Committee 3",
                "org_group_id": 1003,
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    db_conn.execute(
        """
        INSERT INTO cf.nc_orchestrator_progress
            (sboe_id, window_start, window_end, status, claimed_at)
        VALUES
            ('STA-R-001', %(window_start)s, %(window_end)s, 'pending', NULL),
            ('STA-R-002', %(window_start)s, %(window_end)s, 'pending', NULL),
            (
                'STA-R-003',
                %(window_start)s,
                %(window_end)s,
                'in_progress',
                now() - interval '90 minutes'
            )
        """,
        {"window_start": _WINDOW_START, "window_end": _WINDOW_END},
    )

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        allowlist_sboe_ids=["STA-R-001"],
    )

    assert result.seeded == 0
    assert result.reclaimed == 0
    assert result.claimed == 1
    assert result.completed == 1

    statuses = db_conn.execute(
        """
        SELECT sboe_id, status
        FROM cf.nc_orchestrator_progress
        ORDER BY sboe_id ASC
        """
    ).fetchall()
    assert statuses == [
        ("STA-R-001", "completed"),
        ("STA-R-002", "pending"),
        ("STA-R-003", "in_progress"),
    ]


def test_orchestrator_demotes_committee_to_permanent_after_n_attempts(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A committee that fails per_committee_max_attempts times must be marked
    permanent (not retryable) so the claim loop stops re-picking it.

    Why: the 2026-04-26 unbounded re-dispatch hit the consecutive-retry
    budget on a single committee (079-7SE7OZ-C-001, attempt_count=4) that
    kept getting re-claimed and re-failing, blocking the rest of the queue.
    """
    rows = [
        {
            "sboe_id": "STA-Z-001",
            "committee_name": "Always Fails",
            "org_group_id": 300,
            "last_filing_date": None,
            "is_active": True,
        },
    ]
    create_minimal_registry(db_conn, rows)

    transaction_download = MagicMock(side_effect=RuntimeError("portal returns nothing"))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        consecutive_retryable_budget=10,  # disable streak break for this test
        per_committee_max_attempts=3,
    )

    # The committee fails 3 times; the 3rd failure DEMOTES to permanent and
    # the orchestrator does not re-claim it. So total claims == 3.
    assert result.claimed == 3
    assert result.permanent_failures == 1
    assert result.retryable_failures == 2

    rows_after = db_conn.execute("SELECT sboe_id, status, attempt_count FROM cf.nc_orchestrator_progress").fetchall()
    assert len(rows_after) == 1
    assert rows_after[0][0] == "STA-Z-001"
    assert rows_after[0][1] == "failed"


def test_orchestrator_sanitizes_sboe_id_before_building_work_paths(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "../STA/../../evil\nid",
                "committee_name": "Committee 1",
                "org_group_id": 4001,
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    captured_paths: list[Path] = []

    def _capture_committee_docs(_org_group_id: str, _committee_name: str, output_path: Path) -> None:
        captured_paths.append(output_path)

    def _capture_transactions(_criteria: TransactionSearchCriteria, output_path: Path) -> None:
        captured_paths.append(output_path)

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        _capture_committee_docs,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        _capture_transactions,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
    )

    assert result.completed == 1
    assert len(captured_paths) == 2
    for path in captured_paths:
        assert path.parent == tmp_path
        assert ".." not in path.name
        assert "/" not in path.name
        assert "\n" not in path.name
        path.resolve().relative_to(tmp_path.resolve())
    output_lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(output_lines) == 1
    assert "outcome=completed" in output_lines[0]
    assert "sboe_id=../STA/../../evil" not in output_lines[0]


def test_orchestrator_passes_year_from_to_transaction_load(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-Y-001",
                "committee_name": "Committee 1",
                "last_filing_date": date(2025, 1, 3),
                "is_active": True,
            },
        ],
    )
    mock_load = MagicMock(return_value=_load_result_with_filtered(filtered=4))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        mock_load,
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        year_from=2023,
    )

    assert result.year_filtered == 4
    assert mock_load.call_args.kwargs["year_from"] == 2023


def test_orchestrator_breaks_on_three_consecutive_retryable_failures(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A streak of 3 consecutive retryable failures aborts the run as a
    circuit-breaker against a wedged portal."""
    rows = [
        {
            "sboe_id": f"STA-B-{i:03d}",
            "committee_name": f"Committee {i}",
            "org_group_id": 200 + i,
            "last_filing_date": None,
            "is_active": True,
        }
        for i in range(1, 7)
    ]
    create_minimal_registry(db_conn, rows)

    transaction_download = MagicMock(side_effect=RuntimeError("portal wedged"))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    # Disable the per-committee retry-cap in this test so we isolate the
    # CONSECUTIVE-failure streak break (the cap demotes after N attempts on
    # the same row; that's a different circuit-breaker tested separately).
    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
        consecutive_retryable_budget=3,
        per_committee_max_attempts=99,
    )
    # Should claim and retry exactly 3 committees, then break (not all 6).
    assert result.claimed == 3
    assert result.retryable_failures == 3
    assert result.completed == 0


def test_orchestrator_marks_zero_results_committee_as_completed_not_retryable(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A committee with no transactions in the search window must complete cleanly.

    Why: NC TxnLkup renders 'No Results Found.' inline when the search
    matches zero rows; the export button never appears. Before this fix
    the orchestrator's polling loop ran 120s, then surfaced a misleading
    'Locator.wait_for: Timeout 1ms' which the orchestrator treated as a
    retryable failure that aborted the whole run. Live evidence: 2026-04-25
    bounded prod-proof attempt for sboe_id 001-085N21-C-001 hit exactly
    this pattern.

    The fix raises NCNoTransactionsForCriteriaError (legitimate
    completion), and the orchestrator now marks the committee completed
    with zero rows and continues to the next committee.
    """
    from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
        NCNoTransactionsForCriteriaError,
    )

    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "ZERO-RESULTS-1",
                "committee_name": "Empty Committee A",
                "org_group_id": 100,
                "last_filing_date": None,
                "is_active": True,
            },
            {
                "sboe_id": "ZERO-RESULTS-2",
                "committee_name": "Empty Committee B",
                "org_group_id": 101,
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    committee_download = MagicMock()
    transaction_download = MagicMock(side_effect=NCNoTransactionsForCriteriaError("test"))
    load_with_filings = MagicMock(return_value=_load_result())

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        committee_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        load_with_filings,
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
    )

    # Both zero-result committees must be marked completed (not retryable),
    # and the orchestrator must keep going past the first empty committee.
    assert result.completed == 2, (
        f"Both zero-results committees should be marked completed; got completed={result.completed}, "
        f"retryable={result.retryable_failures}"
    )
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0

    statuses = db_conn.execute("SELECT sboe_id, status FROM cf.nc_orchestrator_progress ORDER BY sboe_id").fetchall()
    assert [(r[0], r[1]) for r in statuses] == [
        ("ZERO-RESULTS-1", "completed"),
        ("ZERO-RESULTS-2", "completed"),
    ]
    # The transaction-load step must NOT be invoked when there's nothing to
    # load (transaction_path was never written).
    assert load_with_filings.call_count == 0


def test_orchestrator_picks_largest_org_group_id_for_duplicate_sboe_ids(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When the same sboe_id is shared by multiple registry rows, pick the largest
    org_group_id deterministically (most recent NC SBoE assignment).

    Why: live 2026-04-25 production data has sboe_id duplicates — at least
    FED-C4753N-C-001 and STA-C1873N-C-002 each map to two distinct
    org_group_id rows. The unique constraint is on org_group_id, not
    sboe_id. Without deterministic ordering, _registry_org_group_id's
    arbitrary `LIMIT 1` would pick a different OGID across runs (or even
    across invocations within a run), making the orchestrator's
    portal-driven ingest non-reproducible. Largest org_group_id is the
    deterministic, reasonable choice (newer registry assignment).
    """
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "DUP-SBOE-001",
                "committee_name": "Older Registration",
                "org_group_id": 100,
                "last_filing_date": None,
                "is_active": True,
            },
            {
                "sboe_id": "DUP-SBOE-001",
                "committee_name": "Newer Registration (same sboe_id)",
                "org_group_id": 200,
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    committee_download = MagicMock()
    transaction_download = MagicMock()
    load_with_filings = MagicMock(return_value=_load_result())

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        committee_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        load_with_filings,
    )

    orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )

    assert committee_download.call_count == 1
    actual_first_arg = committee_download.call_args_list[0].args[0]
    assert actual_first_arg == "200", (
        f"Expected MAX(org_group_id)='200' for duplicate sboe_id, got {actual_first_arg!r}; "
        "non-deterministic ordering would re-introduce flaky orchestrator behavior."
    )


def test_orchestrator_passes_org_group_id_not_sboe_id_to_committee_download(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """download_committee_document_export must receive OGID (org_group_id), not sboe_id.

    Why: the live 2026-04-25 first prod-proof attempt failed with
    `Committee export returned HTML instead of CSV` because the orchestrator was
    calling download_committee_document_export(sboe_id, ...). The CFOrgLkup
    portal expects OGID in the URL; passing sboe_id where OGID is expected
    returns an HTML 404 page, which fails the CSV validator.
    Regression test pins the contract: orchestrator must pass org_group_id.
    """
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-PROOF-0001",
                "committee_name": "Active With Distinct OGID",
                "org_group_id": 999777,
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    committee_download = MagicMock()
    transaction_download = MagicMock()
    load_with_filings = MagicMock(return_value=_load_result())

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        committee_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        load_with_filings,
    )

    orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )

    assert committee_download.call_count == 1
    actual_first_arg = committee_download.call_args_list[0].args[0]
    assert actual_first_arg == "999777", (
        f"Expected org_group_id '999777' (CFOrgLkup OGID) but got {actual_first_arg!r}; "
        "regressed to passing sboe_id which produces 'HTML instead of CSV' in production."
    )
    assert actual_first_arg != "STA-PROOF-0001", (
        "Orchestrator must NOT pass sboe_id to download_committee_document_export"
    )


def test_orchestrator_processes_only_eligible_committees_in_order(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0003",
                "committee_name": "Alpha Recent",
                "last_filing_date": date(2025, 1, 5),
                "is_active": False,
            },
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Stale Inactive",
                "last_filing_date": date(2024, 12, 31),
                "is_active": False,
            },
            {
                "sboe_id": "STA-C0002",
                "committee_name": "Beta Active",
                "last_filing_date": None,
                "is_active": True,
            },
        ],
    )
    committee_download = MagicMock()
    transaction_download = MagicMock()
    load_with_filings = MagicMock(return_value=_load_result())

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        committee_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        load_with_filings,
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
    )

    assert result.seeded == 2
    assert result.completed == 2
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    # download_committee_document_export must receive the CFOrgLkup OGID
    # (org_group_id), not the sboe_id. Passing sboe_id where OGID is expected
    # produces the live "Committee export returned HTML instead of CSV" failure
    # observed in the 2026-04-25 first prod-proof attempt.
    # create_minimal_registry assigns org_group_id by row insertion order:
    #   row 1 STA-C0003 -> 1, row 2 STA-C0001 -> 2, row 3 STA-C0002 -> 3
    # Eligible rows after the orchestrator filter: STA-C0002 (3) and STA-C0003 (1).
    # Claim order is sboe_id ASC: STA-C0002 then STA-C0003.
    assert [call.args[0] for call in committee_download.call_args_list] == ["3", "1"]
    assert [call.args[0].committee_name for call in transaction_download.call_args_list] == [
        "Beta Active",
        "Alpha Recent",
    ]
    assert [call.args[0] for call in load_with_filings.call_args_list] == [db_conn, db_conn]
    assert _status_rows(db_conn) == [
        ("STA-C0002", "completed", 0, None),
        ("STA-C0003", "completed", 0, None),
    ]

    rerun = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=None,
        work_dir=tmp_path,
    )
    assert rerun.completed == 0
    assert rerun.claimed == 0


def test_orchestrator_returns_transient_download_errors_to_pending_state(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Retry Committee",
                "last_filing_date": date(2025, 1, 15),
                "is_active": False,
            },
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(side_effect=RuntimeError("portal timeout")),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )
    assert result.retryable_failures == 1
    assert result.permanent_failures == 0
    assert _status_rows(db_conn) == [("STA-C0001", "pending", 1, "portal timeout")]


def test_orchestrator_marks_deterministic_load_failures_once(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Permanent Failure Committee",
                "last_filing_date": date(2025, 1, 20),
                "is_active": False,
            },
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(side_effect=ValueError("No NC filing join match for transaction row")),
    )

    first = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )
    assert first.permanent_failures == 1
    assert first.retryable_failures == 0
    assert _status_rows(db_conn) == [
        ("STA-C0001", "failed", 1, "No NC filing join match for transaction row"),
    ]

    second = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )
    assert second.claimed == 0
    assert _status_rows(db_conn) == [
        ("STA-C0001", "failed", 1, "No NC filing join match for transaction row"),
    ]


def test_orchestrator_builds_transaction_search_criteria_from_window(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Window Committee",
                "last_filing_date": date(2025, 1, 3),
                "is_active": False,
            },
        ],
    )
    transaction_download = MagicMock()
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        transaction_download,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
    )

    transaction_download.assert_called_once_with(
        TransactionSearchCriteria(
            committee_name="Window Committee",
            date_from="01/01/2025",
            date_to="01/31/2025",
        ),
        tmp_path / "STA-C0001_transactions_2025-01-01_2025-01-31.csv",
    )


def test_orchestrator_commits_per_committee_when_opted_in(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`commit_per_committee=True` must call conn.commit() per terminal outcome.

    Previously the orchestrator held one giant transaction across an
    entire statewide crawl (10k+ committees, hours-long). On crash, all
    progress was lost; mid-run, no other DB session could observe progress.
    This test pins the per-committee commit contract so the architectural
    fix doesn't silently regress.

    The test monkeypatches `db_conn.commit` to a no-op counter so the
    surrounding BEGIN/ROLLBACK isolation is preserved (no test data
    leaks into the real DB).
    """
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": f"STA-C{i:04d}",
                "committee_name": f"Committee {i}",
                "last_filing_date": date(2025, 1, 3),
                "is_active": False,
            }
            for i in range(3)
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    commit_calls: list[None] = []
    monkeypatch.setattr(db_conn, "commit", lambda: commit_calls.append(None))

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=3,
        work_dir=tmp_path,
        commit_per_committee=True,
    )

    assert result.completed == 3
    # At least one commit per completed committee (the success path commits
    # once at end-of-loop). Strict-equality would over-couple to internals.
    assert len(commit_calls) >= result.completed, f"Expected ≥{result.completed} commits, got {len(commit_calls)}"


def test_orchestrator_does_not_commit_when_not_opted_in(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Default `commit_per_committee=False` must preserve test isolation.

    Unit tests share a BEGIN/ROLLBACK fixture connection. If the
    orchestrator were to commit by default, fixture-scoped data would
    leak across tests and corrupt isolation.
    """
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Committee 1",
                "last_filing_date": date(2025, 1, 3),
                "is_active": False,
            },
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    commit_calls: list[None] = []
    monkeypatch.setattr(db_conn, "commit", lambda: commit_calls.append(None))

    orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=1,
        work_dir=tmp_path,
        # default commit_per_committee=False
    )

    assert len(commit_calls) == 0, (
        f"Default must not commit (would leak into BEGIN/ROLLBACK isolation); got {len(commit_calls)} commit calls"
    )


def test_orchestrator_logs_per_committee_terminal_outcome(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every per-committee terminal outcome MUST emit a log line.

    Live incident 2026-04-26: a 1h45m+ orchestrator run produced a
    0-byte log file because nothing was logged per-committee. Only an
    end-of-run summary would have appeared on a clean exit. Operators
    had no way to tell from the log whether the orchestrator was
    advancing or stuck. This test pins per-committee logging so future
    runs always have visible forward-progress evidence.
    """
    create_minimal_registry(
        db_conn,
        [
            {
                "sboe_id": "STA-C0001",
                "committee_name": "Committee 1",
                "last_filing_date": date(2025, 1, 3),
                "is_active": False,
            },
            {
                "sboe_id": "STA-C0002",
                "committee_name": "Committee 2",
                "last_filing_date": date(2025, 1, 3),
                "is_active": False,
            },
        ],
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_committee_document_export",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.download_transaction_export_playwright",
        MagicMock(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest.load_nc_transactions_with_filings",
        MagicMock(return_value=_load_result()),
    )

    result = orchestrate_committee_ingest(
        db_conn,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        stale_after_minutes=30,
        politeness_delay_seconds=0.0,
        limit=2,
        work_dir=tmp_path,
    )

    assert result.completed == 2
    captured = capsys.readouterr()
    # Each committee MUST appear by sboe_id in the captured output so
    # an operator tailing the log file always sees forward progress.
    assert "STA-C0001" in captured.out, f"orchestrator did not log STA-C0001 to stdout; got: {captured.out!r}"
    assert "STA-C0002" in captured.out, f"orchestrator did not log STA-C0002 to stdout; got: {captured.out!r}"
    # And the outcome must be visible — operators need to distinguish
    # completions from failures at a glance.
    assert "completed" in captured.out.lower(), f"orchestrator did not log 'completed' outcome; got: {captured.out!r}"
