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

## Coverage semantics
- The NC package remains a single statewide source package that includes state, county, municipal, and judicial activity via shared NCSBE portals.
- Coverage examples used to prove that cross-jurisdiction reach:
  - `ADAMS FOR NC HOUSE`
  - `JOHN ADCOCK FOR COUNTY COMMISSIONER`
  - `JASON MERRILL FOR CARRBORO TOWN COUNCIL`
  - `RICHARD N ADAMS FOR DIST CT JUDGE`
- Office-level classification is derived from committee identifiers/names and committee-document linkage, because transaction exports do not carry explicit office/county/municipality columns.
