# North Carolina data semantics

`config.yaml` is the authoritative source for NC verification metadata and CSV header contracts. This document describes field meaning and ingest semantics only.

Acquisition workflow details were re-verified against live 2026-cycle transaction exports on 2026-03-21.

## Date fields
- Transaction `Date Occured` values are `MM/DD/YYYY` and normalize to date-only values.
- Committee-document date fields (`Received Image`, `Received Data`, `Start Date`, `End Date`) are `MM/DD/YYYY`.
- No timezone-bearing timestamps are expected from the retained NC export artifacts.

## `Transction Type` classification semantics
- `Transction Type` values drive contributor/payee entity classification, not transaction direction codes.
- Current implemented classification recognizes `Individual` as person-side extraction and `Non-Party Comm` / `Business/Group/Org` as organization-side extraction.
- Unrecognized transaction-type strings map to `"unknown"` in `classify_transction_type()`. When `"unknown"` is returned, neither person nor organization entities are extracted (entity extraction is skipped), but the raw transaction data is preserved in source records for provenance.

## Name, employer, and address semantics
- `Name` is a mixed-role field (donor/payee/counterparty by row context).
- `Profession/Job Title` and `Employer's Name/Specific Field` are optional free text and often blank.
- Address values are flat US-format text fields; ZIP values may contain suffix placeholders.

## Committee identifiers and filing linkage
- `Committee SBoE ID` (transactions) and `SBoE ID` (committee/document export) are the cross-view stable identifier.
- Filing-aware ingest requires an exact key match between:
  - transaction key `(Committee SBoE ID, Report Name)`
  - committee-document key `(SBoE ID, Year + Doc Name)`
- The strict join is enforced in `load.py::_upsert_transaction_with_filing_lookup()`. Missing join matches are treated as load errors.

## Amendment and provenance semantics
- Committee-document rows carry amendment state via `Amend` (`Y`/`N`).
- Transaction rows inherit amendment context through the filing join.
- Blank `Doc Name` committee-document rows can occur in retained real data. Loader behavior keeps `core.source_record` provenance for those rows but excludes them from filing lookup and filing creation.

## Acquisition workflow semantics
- Transaction exports are query-state dependent and require browser automation to reliably produce non-empty CSV output in production ingest.
- Observed transaction workflow endpoints:
  - `/CFTxnLkup/TxnSearchResults/`
  - `/CFTxnLkup/GetPagedResults?page={page}&pageSize={page_size}`
  - `/CFTxnLkup/ExportResults/`
  - Observed result paging contract: `pageSize: 500`
- Committee-document exports are per-committee list exports and remain required input for filing-aware transaction loading.
- Observed committee/document workflow endpoints:
  - `/CFOrgLkup/CommitteeGeneralResult/`
  - `/CFOrgLkup/DocumentGeneralResult/?SID={SBoEID}&OGID={OrgGroupID}`
  - `/CFOrgLkup/ExportSearchResults/?OGID={OrgGroupID}&Title={title}&Type=DocGen`
- There is no known statewide bulk transaction or committee-document export contract.

## `cf.nc_committee_registry` table

Statewide committee registry populated by alphabetic crawl of the `CFOrgLkup` portal via `crawl_committee_registry_httpx()`.

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `org_group_id` | integer (PK) | NCSBE internal org-group identifier; UPSERT key |
| `sboe_id` | text | SBoE committee ID (e.g. `STA-C0498N-C-002`) |
| `committee_name` | text | Official registered committee name |
| `status_desc` | text | Registration status (`Active`, `Dissolved`, `Inactive`, etc.) |
| `old_id` | text | Legacy identifier from prior NCSBE system |
| `candidate_name` | text | Associated candidate name (null for non-candidate committees) |
| `data_source_id` | integer | Source identifier from portal JSON payload |
| `first_seen_at` | timestamptz | Earliest crawl that observed this committee (LEAST on UPSERT) |
| `last_seen_at` | timestamptz | Most recent crawl that observed this committee (GREATEST on UPSERT) |

### Source

Alphabetic enumeration of `https://cf.ncsbe.gov/CFOrgLkup/` — 26 letter-prefix searches (A-Z) with JSON response parsing from inline `window.dt` payloads.

### UPSERT contract

Keyed on `org_group_id`. On conflict: advances `last_seen_at` to current timestamp via `GREATEST(last_seen_at, EXCLUDED.last_seen_at)`, retains earliest `first_seen_at` via `LEAST(first_seen_at, EXCLUDED.first_seen_at)`.

### Row count

13,612 rows as of the Stage 5 proof (2026-04-25). Idempotent rerun confirmed: `inserted=0 updated=0 skipped=13612`.

## Coverage semantics
- The NC package remains a single statewide source package that includes state, county, municipal, and judicial activity via shared NCSBE portals.
- Office-class evidence is proven at the committee-document level: committee-name patterns and `SBoE ID` identifiers from the committee/document portal (`CFOrgLkup`) provide the office-class signal, since transaction CSV exports carry no office column. The evidence path is committee-name token matching joined through `(SBoE ID, Year + Doc Name)` committee-document keys.
- Coverage examples anchoring all five in-scope office classes:
  - `ADAMS FOR NC HOUSE` (state_house)
  - `GALE ADCOCK FOR NC SENATE` (state_senate)
  - `JOHN ADCOCK FOR COUNTY COMMISSIONER` (county)
  - `JASON MERRILL FOR CARRBORO TOWN COUNCIL` (municipal)
  - `RICHARD N ADAMS FOR DIST CT JUDGE` (judicial)
