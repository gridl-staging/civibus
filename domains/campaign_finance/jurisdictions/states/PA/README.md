# Pennsylvania (PA) campaign-finance jurisdiction package

## Jurisdiction overview
Pennsylvania is a state-level jurisdiction (`fips: 42`) using Department of State (DOS) full-export ZIP archives. Despite URL labeling as "yearly," the current-year ZIP is regenerated roughly weekly (~4 day lag from latest filing). See `docs/reference/research/pa-freshness-investigation-2026-03-28.md`.

`config.yaml` is the only machine-readable source of truth for PA archive URLs, source names, coverage, and field mappings.

## Data freshness (verified 2026-03-28)
- **Update frequency:** Weekly (current-year ZIP regenerated ~weekly, verified via HTTP Last-Modified headers)
- **Lag:** ~4 days from latest filing SubmittedDate to ZIP publication
- **All reporting cycles included:** Annual, Pre-Primary, Post-Primary, Pre-Election, Post-Election, 24-hour — all present in yearly ZIPs as filings arrive
- **SODA API:** Exists on data.pa.gov but access-restricted (403, requires login)
- **CFOnline portal:** Behind Incapsula, temporarily unavailable as of 2026-03-28

## Archive shape summary (verified)
Observed 2025 full-export archive members:
- `contrib_2025.txt`
- `expense_2025.txt`
- `debt_2025.txt`
- `filer_2025.txt`
- `receipt_2025.txt`

Data-quality facts locked from Stage 1 evidence:
- `contrib_2025.txt` and `expense_2025.txt` require `cp437` decoding.
- `debt_2025.txt`, `filer_2025.txt`, and `receipt_2025.txt` decode as UTF-8.
- Detail files use `CampaignFinanceID`; filing index uses `CampaignfinanceID` (capitalization differs), so amendment inheritance requires filing-index linkage.

## Stage boundary notes
- This jurisdiction package ships downloader, parser, extract, load, and CLI modules for PA annual DOS full-export ZIP archives.
- The annual DOS full-export ZIP remains the canonical ingest contract; the PA online database exists but machine export/API + scope parity are unverified.
- `filings` rows are parse/dry-run only for this package and support amendment enrichment joins; standalone `filings` refresh loads are intentionally rejected.

## Sources
- PA DOS campaign-finance data portal (canonical annual full-export ZIP source): <https://www.pa.gov/agencies/dos/resources/voting-and-elections-resources/campaign-finance-data>
- PA online campaign-finance database (official interactive surface; machine export/API + scope parity unverified): <https://www.campaignfinanceonline.pa.gov/pages/CFReportSearch.aspx>
- Stage 1 verified semantics: `domains/campaign_finance/jurisdictions/states/PA/data_semantics.md`
- Stage 1 member inventory and encoding evidence: `domains/campaign_finance/jurisdictions/states/PA/sample_rows/member_inventory.tsv` and `domains/campaign_finance/jurisdictions/states/PA/sample_rows/encoding_check.tsv`
