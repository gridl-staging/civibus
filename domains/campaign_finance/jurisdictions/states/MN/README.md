# Minnesota (MN) campaign-finance jurisdiction package

## Jurisdiction overview
Minnesota is a state-level jurisdiction (`fips: 27`) using direct CSV downloads published by the Minnesota Campaign Finance and Public Disclosure Board.

This package covers the MN board campaign-finance download surface and keeps `config.yaml` as the single machine-readable source of truth for endpoint IDs, coverage, and field mappings.

The canonical ingest contract is the quarterly direct-download `?download=` CSV feed set declared in `config.yaml` and consumed by the shipped downloader/CLI path.

## Data sources summary
MN publishes three direct CSV download surfaces from the same landing page:

| Source | Transaction type | Direct endpoint shape |
|---|---|---|
| MN CFB Contributions (All) | contributions | `...?download=-2113865252` |
| MN CFB Expenditures (All) | expenditures | `...?download=-1890073264` |
| MN CFB Independent Expenditures (All) | independent_expenditures | `...?download=-617535497` |

- Landing page: `https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/`
- Format: CSV
- Auth: none
- Update frequency: quarterly
- Coverage baseline: 2015 to present

## Coverage notes
`coverage.covers_sub_jurisdictions` remains `false` for all MN data sources.

Reason: the board publishes a separate local-reporting surface for local campaign finance reports:
`https://register.cfb.mn.gov/reports-and-data/searches-and-lists/other-reports-and-lists/local-campaign-finance-reports/`

## Known data quality issues
- Download links are parameterized by `?download=<id>` and IDs are externally managed; endpoint IDs may drift.
- CSV headers are controlled by the board export and must be validated against config mapping order.
- Stage 3 loader ingests contributions and expenditures; independent expenditures remain documented in config/docs only.
- The IE-only `For /Against` column is preserved as the MN-local semantic path `mn.independent_expenditure.support_oppose` until shared schema support exists.
- `/reports/#/` and `/reports/api/` are supplemental evidence surfaces only and are not required for canonical ingest.

## Last verified date
- Source access and endpoint IDs verified: 2026-03-21
- Laws research verified: 2026-03-21

## Update instructions
1. Re-open the MN campaign-finance landing page and confirm current `?download=` IDs.
2. Pull each direct CSV and verify header order matches `config.yaml` field mappings.
3. Re-run `make validate-configs` and MN parser/load tests.
4. Update `config.yaml` verification dates and notes if IDs or header shapes change.
