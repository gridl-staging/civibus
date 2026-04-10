# Washington campaign-finance data semantics

This document captures parser and extraction assumptions for WA PDC Socrata CSV datasets. Machine-readable mapping authority remains in `config.yaml`.
For ingest scope and source availability, use README.md and config.yaml as the truth surfaces.

## Date fields
- Contributions: `receipt_date`
- Expenditures: `expenditure_date`
- Loans: `receipt_date`
- Values are emitted as ISO-like timestamp strings (for example `2025-01-15T00:00:00.000`) and normalized to dates for filing/transaction load.

## Name formats
- Contributions: donor identity from `contributor_name`
- Expenditures: payee identity from `recipient_name`
- Loans: lender identity from `lenders_name`
- Names may appear as person-style `Last, First` or organization names.

## Employer/occupation
- Contributions include donor employer/occupation fields.
- Loans include lender employer/occupation fields.
- Expenditures do not provide reliable employer/occupation for payees in this dataset shape.

## Address format
- Donor/payee/lender address rows are treated as street1 + city + state + zip in Stage 4.
- Empty components normalize to null.
- Zip values are normalized into zip5/zip4 when possible.

## Committee IDs
- Committee identifier is `committee_id` across WA contributions, expenditures, and loans datasets.
- Committee IDs are mapped into organization identifiers as `wa_committee_id`.

## Amendment handling
- WA Stage 4 ingestion treats each row as a source-record keyed event from current API extracts.
- No WA-specific amendment graph is introduced in this stage.

## Missing/null conventions
- Empty CSV cells normalize to null.
- Malformed rows (width mismatch relative to expected header) are skipped and counted as quarantined parser rows.

## Portal Navigation
WA Stage 4 uses direct API-backed CSV URLs and does not require browser automation:
1. Entry page: `https://www.pdc.wa.gov/political-disclosure-reporting-data/open-data`
2. Confirm dataset IDs on `data.wa.gov` metadata pages.
3. Fetch CSV through `https://data.wa.gov/resource/{dataset_id}.csv`.
4. Validate header order against `config.yaml` field mappings.
