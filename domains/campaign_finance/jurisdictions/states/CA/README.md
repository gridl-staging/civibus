# California (CA) campaign-finance jurisdiction package

## Jurisdiction overview
California is a state-level jurisdiction (`fips: 06`) sourced from CAL-ACCESS raw extracts published by the California Secretary of State. This package targets campaign-finance ingestion for Stage 2 from direct-download tab-delimited members only; lobbying coverage is documented but out of ingest scope for this stage. [S1][S2]

## Data sources summary
`config.yaml` remains the only machine-readable source of truth.

- CAL-ACCESS Raw Data Export (`dbwebexport.zip`): daily-updated tab-delimited raw extracts. [S1][S3]
- CAL-ACCESS Documentation Bundle (`calaccess-documentation.zip`): table/field guides used as reference only. [S1][S2]

Stage 2 locked ingestion members (from `config.yaml` field-mapping table set):
- `CalAccess/DATA/CVR_CAMPAIGN_DISCLOSURE_CD.TSV`
- `CalAccess/DATA/RCPT_CD.TSV`
- `CalAccess/DATA/EXPN_CD.TSV`
- `CalAccess/DATA/LOAN_CD.TSV`
- `CalAccess/DATA/FILERNAME_CD.TSV`
- `CalAccess/DATA/FILERS_CD.TSV` [S2][S3]

Documentation-only (not loaded in Stage 2): lobbying tables, schedule/memo/split tables, and additional linkage/reference tables not required by current filing/transaction model. [S2]

## Coverage notes
- `coverage.start_year: 1999` uses campaign-disclosure baseline from sampled data.
- `coverage.covers_sub_jurisdictions: true` is supported by sampled local/county office and jurisdiction codes (`JURIS_CD`/`OFFICE_CD` evidence in RCPT/EXPN/CVR). [S3][S4]
- `LOAN_CD` includes pre-2000 historical dates (observed through 1990), documented as a known issue rather than redefining campaign baseline. [S4]

## Known data quality issues
- Archive size is operationally large (~1.5 GB compressed), and large transaction members require ZIP64-aware handling.
- Date anomalies exist (`0200`, `1899`, `1982`, isolated `1970` in sampled EXPN).
- Jurisdiction/office descriptors are inconsistent across rows.
- Documentation bundle is legacy-dated and cannot be treated as authoritative over live sampled extracts.
- Although source declares tab-delimited text, `format` in schema remains `csv` for cross-state contract compatibility. [S1][S2][S4]

## Last verified date
- Source access and archive URL reachability: 2026-03-26.
- Coverage verification sample analysis: 2026-03-18.
- Laws references: 2026-03-21. [S2][S4][S5][S6][S7]

## Update instructions
1. Re-verify source reachability (`raw data` page + ZIP URLs).
2. Re-run member inventory checks against `dbwebexport.zip` and confirm Stage 2 six-member lock remains valid.
3. Re-sample CVR/RCPT/EXPN/LOAN date floors and jurisdiction indicators; update `coverage.*` or `known_issues` only in `config.yaml`.
4. Re-verify campaign-law values/notes against current FPPC and statute sources, then sync narrative docs to `config.yaml`.

## Open questions
- Current FPPC 2025-2026 published office-tier limits appear to differ from simplified flat values currently stored in `config.yaml`; schema-level policy is needed on which office tier to encode in the flat `contribution_limits` block. [S5][S3]
- Additional CA members (`FILER_FILINGS_CD`, schedule/memo tables) may become necessary for later-stage reconciliation, but are intentionally excluded from Stage 2 schema scope. [S2]

## Sources
- [S1] https://www.sos.ca.gov/campaign-lobbying/cal-access-resources/raw-data-campaign-finance-and-lobbying-activity
- [S2] `docs/research/stage2-ca-archive-member-investigation.md`
- [S3] `domains/campaign_finance/jurisdictions/states/CA/config.yaml`
- [S4] `docs/research/stage2-ca-coverage-verification.md`
- [S5] https://www.fppc.ca.gov/learn/campaign-rules/state-contribution-limits-and-voluntary-expenditure-ceilings/
- [S6] https://www.sos.ca.gov/campaign-lobbying/helpful-resources/how-to-file-electronically
- [S7] https://www.leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?article=2.&chapter=4.&division=&lawCode=GOV&part=&title=9.
