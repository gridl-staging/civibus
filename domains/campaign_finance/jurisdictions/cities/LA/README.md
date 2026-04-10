# Los Angeles (LA) campaign-finance jurisdiction package

## Jurisdiction overview
Los Angeles is a municipality-level jurisdiction (`fips: 06037`) with parent state `CA`.
This package defines the LA city campaign-finance pipeline for the Civibus city pipeline pattern.

## Data sources summary
- Primary source: LA City Ethics Commission campaign-finance disclosures via data.lacity.org (Socrata).
- Landing page: `https://ethics.lacity.gov/data/campaigns/contributions/`
- Dataset (contributions): `m6g2-gc6c`
- Access pattern: SODA API + CSV export (`format: api` in config)
- Refresh profile: daily updates (modeled as `update_frequency: daily`)
- Row count: 388,645+ as of 2026-04-08

Note: The primary portal (`ethics.lacity.gov`) returns HTTP 403 to automated fetches.
The `data.lacity.org` Socrata portal is the programmatic alternative.

## Coverage notes
- `coverage.covers_sub_jurisdictions` is `false` because this source is specific to the City of Los Angeles.
- The contributions dataset covers itemized monetary contributions to LA city candidates and committees.
- Expenditures, independent expenditures, and other transaction types require separate datasets (not yet mapped).

## Known data quality issues
- Some rows have null `cmt_id` values; committee identity falls back to namespaced committee name.
- The contributions dataset (`m6g2-gc6c`) is a single transaction type; full coverage requires additional datasets.

## Last verified date
- Source access and dataset ID verified: 2026-04-08
- Laws notes synchronized with config laws block: 2026-04-08
