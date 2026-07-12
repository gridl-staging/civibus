# North Carolina (NC) campaign-finance jurisdiction package

## Jurisdiction overview
This package covers North Carolina as a single statewide campaign-finance source package (`jurisdiction.code = NC`) while explicitly including state, county, municipal, and judicial activity surfaced through NCSBE's centralized `cf.ncsbe.gov` portals.

## Source-of-truth boundaries
- `config.yaml` is the authoritative NC source for verification metadata (`last_verified_working`, `known_issues`) and CSV header contract (`field_mappings`).
- Runtime contract consumers:
  - `domains/campaign_finance/jurisdictions/states/NC/scraper/__init__.py::_find_nc_data_source_block()`
  - `domains/campaign_finance/jurisdictions/states/NC/scraper/parse.py::_load_columns()`

## Data sources summary
- **North Carolina SBoE Transaction Search** (`https://cf.ncsbe.gov/CFTxnLkup/`)
  - Format: `web_portal`
  - Access pattern: query-driven results + CSV export
  - No official bulk/API contract observed.
  - Browser automation is required for reliable export execution. `download_transaction_export_playwright()` is the supported acquisition path for production transaction exports.
  - As of 2026-03-27, reliable committee-scoped downloads require filling the visible committee text field alongside the committee ID; the old hidden-name-only path triggered `GetPagedResults` `502` responses and never reached an exportable results grid.
- **North Carolina SBoE Committee/Document Search** (`https://cf.ncsbe.gov/CFOrgLkup/`)
  - Format: `web_portal`
  - Access pattern: committee lookup -> document list -> per-committee CSV export
  - Used for filing metadata required by filing-aware NC transaction ingest.
  - Export scope is per committee; no statewide bulk document-index export contract exists.

### IE Document Index
- **North Carolina SBoE IE Document Index** (`https://cf.ncsbe.gov/CFDocLkup/`)
  - Classification: `T1` from Hetzner for this lane (`httpx.get` direct CSV response from `/CFDocLkup/ExportSearchResults/`; no browser automation required for the export contract).
  - Scope: statewide filing-document index metadata (`Committee Name`, `SBoE ID`, `Doc Name`, period boundaries, DATA/IMAGE links). Transaction-level IE amounts are recovered downstream from each filing's linked `CFOrgLkup` `ReportDetail` export.
  - Operational proof: 2026-04-19 Hetzner live load inserted 47 NC IE filing-index rows (`NC-IE-%`) with idempotent rerun (`inserted=0` on second pass).
  - Evidence paths:
    - Canonical repo-owned investigation and Stage 4 proof summary: `docs/reference/research/nc_ie_portal_investigation_2026_04_18.md`
    - Supporting local probe artifacts: `docs/reference/research/artifacts/2026_04_18_nc_ie/`
    - Transaction-amount contract re-probe: `docs/reference/research/nc_ie_transaction_amounts_investigation_2026_04_25.md`

## Coverage notes
- Retained Stage 3/4 fixtures prove the NC package contract for:
  - non-empty transaction export ingestion (`real_transaction_export_adams.csv`)
  - committee-document filing metadata ingestion for `STA-C3219N-C-001` (`real_committee_doc_export_3517.csv`)
  - blank-`Doc Name` committee-document provenance retention without filing creation
- Per-class office coverage is proven at the committee-document level via `tests/test_office_class_coverage.py` for five office classes: `state_house`, `state_senate`, `county`, `municipal`, `judicial`. NC transaction CSVs carry no office column, so office-level classification uses committee-name evidence tokens from committee/document portal exports — not transaction-level office tagging.
- Coverage examples used to prove all in-scope office classes:
  - `ADAMS FOR NC HOUSE` (state_house)
  - `GALE ADCOCK FOR NC SENATE` (state_senate)
  - `JOHN ADCOCK FOR COUNTY COMMISSIONER` (county)
  - `JASON MERRILL FOR CARRBORO TOWN COUNCIL` (municipal)
  - `RICHARD N ADAMS FOR DIST CT JUDGE` (judicial)

## Filing-aware ingest behavior (current)
- `load_nc_transactions_with_filings()` loads committee-document rows first, then transactions, and builds relational `cf.transaction -> cf.filing -> cf.committee` links.
- The earlier production priming-pass workaround turned out to be deployed-runtime drift, not the current repo contract. Focused NC loader tests already prove that committee-document rows can create the missing committee bridge, and the refreshed deployed runtime now exposes the matching `_resolve_nc_committee_bridge(..., committee_name=...)` path.
- `_upsert_transaction_with_filing_lookup()` enforces strict matching on `(Committee SBoE ID, Report Name)` normalized to committee-document `(SBoE ID, Year + Doc Name)` lookup keys.
- Real committee-document rows with blank `Doc Name` are retained in `core.source_record` provenance but intentionally excluded from filing lookup and filing creation.

## Evidence references used for current status
- Stage 3 live browser proof:
  - `domains/campaign_finance/jurisdictions/states/NC/scraper/test_download_playwright.py::test_download_transaction_export_playwright_integration_returns_nonempty_parseable_file`
  - Repo-owned contract investigation and retained artifacts summarized in `docs/reference/research/nc_ie_portal_investigation_2026_04_18.md`
- Stage 4 retained real-data ingest proof:
  - `domains/campaign_finance/jurisdictions/states/NC/scraper/test_load_stage4_real_data.py::test_real_data_transactions_with_filings_builds_relational_chain`
  - `domains/campaign_finance/jurisdictions/states/NC/scraper/test_load_stage4_real_data.py::test_real_committee_docs_blank_doc_name_rows_keep_source_record_provenance`
- Stage 5 bounded runner proof:
  - `python -m core.refresh.runner --scope all --job-key-prefix state-nc --nc-committee-docs-path docs/reference/research/artifacts/2026-03-live-proof/nc_committee_docs_3517.csv --nc-committee-id STA-C3219N-C-001 --nc-committee-name "NC REALTORS PAC" --nc-date-from 01/01/2024 --nc-date-to 01/31/2024 --force`
  - Result: `state-nc-transactions: status=success metadata_updates=1 message=Refresh job succeeded`
- Stage 6 broader committee + production proof:
  - `ADAMS FOR NC HOUSE` / `STA-B6IP24-C-001` retained artifacts at `docs/reference/research/artifacts/2026-03-production-proof/nc_committee_docs_27075_current.csv` and `docs/reference/research/artifacts/2026-03-production-proof/nc_transactions_adams_2024_current.csv`
  - Production proof on 2026-03-28 loaded `65` NC transactions and `54` NC filings into the deployed stack after a transactions-only priming pass plus the filing-aware rerun.

## Verification cadence
- Source access and workflow verified: 2026-04-25
- Laws research verified: 2026-03-14
- Re-verify by running a transaction search and confirming the portal still reaches export-ready results.
- Re-run committee/document evidence checks after any portal workflow or filing-page change.

## Known limitations
- **Contributor/payee role-splitting not yet implemented.** The `Name`, address, occupation, and employer fields in `config.yaml` map to generic `participant.*` paths. Role differentiation will require cross-referencing `Transction Type` during normalization.
- **Unrecognized transaction types.** `classify_transction_type()` returns `"unknown"` for values not in the recognized set (`Individual`, `Non-Party Comm`, `Business/Group/Org`). Entity extraction is skipped for unknown types; raw data is preserved in source records.

## Remaining closeout gap
- Office-class boundary proof (Stage 1 universe table in `docs/reference/research/nc_office_universe_2026_04_24.md` + Stage 3 per-class coverage tests) is complete for all five in-scope classes; the Stage 5 closeout matrix (`docs/reference/research/nc_office_coverage_closeout_2026_04_24.md`) and registry narrative update are the remaining deliverables.
