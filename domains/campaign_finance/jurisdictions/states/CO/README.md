# Colorado (CO) — Campaign Finance Jurisdiction Config

## Jurisdiction overview

Colorado is a state-level jurisdiction (FIPS 08) with campaign finance data administered by the Colorado Secretary of State through the TRACER system (Transparency in Contribution and Expenditure Reporting). Governed by Colorado Constitution Article XXVIII (Amendment 27, 2002) and C.R.S. Title 1, Article 45 (Fair Campaign Practices Act).

This config covers all Colorado state, county, municipal, and special district campaign finance filings reported through TRACER.

## Data sources summary

Three bulk download sources from TRACER, all CSV format in ZIP archives:

| Source | Transaction Type | URL Pattern |
|---|---|---|
| ContributionData | Contributions | `{YEAR}_ContributionData.csv.zip` |
| ExpenditureData | Expenditures | `{YEAR}_ExpenditureData.csv.zip` |
| LoanData | Loans | `{YEAR}_LoanData.csv.zip` |

- **Base URL**: `https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/`
- **Format**: CSV in ZIP, year-partitioned (one file per year per type)
- **Year range**: 2000–2026 verified
- **Auth**: None required for bulk downloads
- **Update frequency**: Weekly (observed: 2026 bulk ZIPs refreshed March 10–12, mid-quarter; documented quarterly cadence unsupported by file timestamps)
- **Field key**: [DownloadDataFileKey.pdf](https://tracer.sos.colorado.gov/PublicSite/Resources/DownloadDataFileKey.pdf) (revised 07/2011)
- Current ingest support: contributions and expenditures are ingest-supported; loans remain source-available only.

## Coverage notes

`covers_sub_jurisdictions: true` — The Jurisdiction field in CSV data contains values including STATEWIDE (state-level races), county names (DENVER, JEFFERSON, BOULDER, etc.), and FEDERAL. County and municipal races are included in the same bulk download files as state-level races.

In the 2025 contributions file (160K records):
- 113K STATEWIDE records
- 47K distributed across 50+ counties
- 1.4K FEDERAL records

Office levels covered: governor, AG, SOS, treasurer, state senate, state house, DA, CU Regent, State Board of Education, county offices, municipal offices, school district directors, RTD directors.

## Known data quality issues

- **LLC contribution type encoding**: ContributionType field embeds LLC total amount as a string suffix (e.g., `Monetary (Itemized) - LLC Contribution (Total Amount: 500.00)`). Requires parsing to extract base type and total amount.
- **LLC contributor type encoding**: ContributorType embeds LLC member name (e.g., `Individual (Member of LLC: HOWES WOLF LLC)`). Requires parsing for clean entity resolution.
- **Cross-year records**: Year-partitioned files are keyed by FiledDate, not transaction date. A record with ContributionDate in 2022 can appear in the 2025 file if filed/amended in 2025.
- **Employer/Occupation in expenditures**: Columns present but documented as unused. Should be ignored for expenditure records.
- **Malformed contribution rows**: 2025 contribution data includes at least 14 rows with broken quoted names that reduce row width from 29 columns to 26. Ingestion should enforce row-length validation and quarantine malformed rows.
- **SSL certificate**: TRACER domain may require custom SSL handling (observed `unable to verify the first certificate` in some environments). Insecure TLS retry is break-glass only and requires both CLI `--allow-insecure-tls` and `CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1`.

See `data_sources[].known_issues` in `config.yaml` and `data_semantics.md` for full details.

## Last verified date

- Source access verified: 2026-03-26 (all three TRACER 2026-cycle bulk URLs confirmed reachable)
- Laws research verified: 2026-03-21
- Sample data inspected: 2025 ContributionData (160,230 records, file dated 2025-02-27)

## Update instructions

1. **Refresh data**: Download new year files from `https://tracer.sos.colorado.gov/PublicSite/DataDownload.aspx`. Files are cumulative within each year — re-download the current year file to capture new filings.
2. **Check contribution limits**: Colorado adjusts limits every 4 years by CPI. Current limits effective 2023-02-15. Next adjustment expected 2027. Check [SOS limits page](https://www.coloradosos.gov/pubs/elections/CampaignFinance/limits/contributions.html).
3. **Verify field key**: The TRACER field key was last revised 07/2011. If CSV column headers change, update `field_mappings` in `config.yaml` and re-verify against `data_semantics.md`.
4. **Check SOS terms**: Portal terms at https://www.coloradosos.gov/pubs/info_center/terms.html may change. See `docs/research/data-licensing.md` for current constraints.
5. **Update `laws.last_verified`** and `last_verified_working` dates after each refresh.
