# Texas (TX) campaign-finance jurisdiction package

## Jurisdiction overview
Texas is a state-level jurisdiction (`fips: 48`) using Texas Ethics Commission (TEC) bulk CSV data exported as a single ZIP archive containing all campaign finance transaction files.

This package keeps `config.yaml` as the only machine-readable source of truth for archive URLs, coverage, and field mappings.

## Data sources summary
TEC publishes campaign finance data as a single bulk ZIP archive (`TEC_CF_CSV.zip`) containing 135 CSV members. Three transaction types are in scope:

| Source | Transaction type | File pattern | Column count |
|---|---|---|---|
| TEC Campaign Finance — Contributions | contributions | `contribs_*.csv` | 37 |
| TEC Campaign Finance — Expenditures | expenditures | `expend_*.csv` | 38 |
| TEC Campaign Finance — Loans | loans | `loans.csv` | 146 |

- Landing page: `https://www.ethics.state.tx.us/search/cf/`
- Bulk archive: `https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip`
- Format: CSV (comma-delimited, selective quoting, UTF-8)
- Auth: none
- Update frequency: daily

## Coverage notes
- `coverage.start_year: 2000` — archive contains filings from 2000 onward.
- `coverage.covers_sub_jurisdictions: true` — archive includes both state and local filings.
- Loans CSV contains 5 repeating guarantor blocks (guarantor1–5) with identical field layouts, denormalized in source.

## Known data quality issues
- `infoOnlyFlag='Y'` marks rows superseded by a later report; maps to `amendment_indicator='T'` but downstream loaders may choose to skip these rows.
- Date format is `YYYYMMDD` (8 digits, no separators); optional dates can be blank.
- All three transaction types share the same bulk ZIP; file selection is by filename prefix.

## Last verified date
- Archive access, headers, and encoding verified: 2026-03-21
- Laws/restriction notes verified: 2026-03-21

## Update instructions
1. Re-download `TEC_CF_CSV.zip` and verify CSV headers still match `config.yaml` field mapping order.
2. Re-run `make validate-configs` and TX scraper tests.
3. If headers change, update `config.yaml`, `data_semantics.md`, and this README in the same change.
