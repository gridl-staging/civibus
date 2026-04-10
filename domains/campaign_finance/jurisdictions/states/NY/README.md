# New York (NY) campaign-finance jurisdiction package

## Jurisdiction overview
New York is a state-level jurisdiction (`fips: 36`) using the NYS Board of Elections campaign finance data via the data.ny.gov SODA API. Contributions and expenditures are in separate filtered datasets with identical 45-column schemas, updated daily.

## Data sources
- **Contributions**: dataset `4j2b-6a2j` (~2.5M rows for 2022+, Schedules A/B/C/D/G)
- **Expenditures**: dataset `ajsb-8pni` (~660K rows for 2022+, Schedule F)
- **Filers**: dataset `7x2g-h32p` (~64K rows, all active + terminated)

## Pipeline
Download → Parse → Extract → Load (two-pass: source records + entities, then filings + transactions). Paginated SODA queries at 50K rows/request with `sched_date >= 2022-01-01` filter.
