# Virginia (VA) campaign-finance jurisdiction package

## Jurisdiction overview
Virginia is a state-level jurisdiction (`fips: 51`) using the Virginia Department of Elections SBE CSV bulk export surface at `https://apps.elections.virginia.gov/SBE_CSV/CF/`.

This package treats `config.yaml` as the single machine-readable source of truth for endpoint URLs, cadence, and field mappings.

## Verified export contract
The official SBE CSV exports are organized by monthly directories (`YYYY_MM/`):
- `https://apps.elections.virginia.gov/SBE_CSV/CF/{YYYY_MM}/ScheduleA.csv` (contributions)
- `https://apps.elections.virginia.gov/SBE_CSV/CF/{YYYY_MM}/ScheduleD.csv` (expenditures)
- `https://apps.elections.virginia.gov/SBE_CSV/CF/{YYYY_MM}/Report.csv` (filing metadata)

Observed response contract:
- No bot protection (requires only User-Agent header)
- Data from 1999 to present
- Daily updates
- Standard quoted CSV format

## Package scope
- Config-driven download/parse/extract/cli seams for Virginia
- Three data sources: contributions (ScheduleA), expenditures (ScheduleD), reports (Report)
- Load.py is a stub pending live data validation
- 38 passing tests covering parse, download, extract, and CLI modules

## Data types
| Data Type | CSV File | Columns |
|-----------|----------|---------|
| contributions | ScheduleA.csv | 22 |
| expenditures | ScheduleD.csv | 20 |
| reports | Report.csv | 39 |

## Key VA-specific details
- `IsIndividual` field (string 'True'/'False') determines person vs. org extraction
- Monthly directory structure requires `--year-month YYYY_MM` for downloads
- VA has no contribution limits for state-level candidates
- Mixed date formats in report data (MM/DD/YYYY vs YYYY-MM-DD HH:MM:SS.nnnnnnnnn)

## Update instructions
1. Re-verify the SBE endpoint responses and header order for each CSV type.
2. Update `config.yaml` `last_verified_working` values when the contract is confirmed.
3. Run VA scraper tests and config validation before any runner wiring changes.
