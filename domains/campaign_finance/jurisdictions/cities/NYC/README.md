# New York City (NYC) campaign-finance jurisdiction package

## Jurisdiction overview
New York City is a municipality-level jurisdiction (`fips: 36061`) with parent state `NY`.
This package defines the NYC city campaign-finance pipeline for the Civibus city pipeline pattern.

## Data sources summary
- Primary source: NYC Campaign Finance Board (CFB) bulk CSV downloads from the Data Library.
- Data Library: `https://www.nyccfb.info/follow-the-money/data-library/`
- Access pattern: Direct HTTP GET for CSV files per election cycle (T1 — no API, no pagination).
- Bulk ZIP: `https://www.nyccfb.info/DataLibrary/CFB-Data.zip` contains all datasets.
- Refresh profile: monthly updates based on observed Data Library revision dates.
- Dataset: Contributions (52 columns per Contribution Key reference).

## Coverage notes
- `coverage.covers_sub_jurisdictions` is `false` because this source is specific to NYC.
- The contributions dataset covers donations to NYC city candidates and committees.
- NYC CFB is the mandatory public matching funds program for city races.
- Expenditures, intermediaries, and public funds payments are separate datasets (not yet mapped).

## Known data quality issues
- CSV files are organized by election cycle; historical coverage requires downloading multiple files.
- Some rows may have empty RECIPID or COMMITTEE values for certain schedule types.
- Monthly cadence is below the weekly launch threshold for election coverage.

## Last verified date
- Source access and Data Library structure verified: 2026-04-08
- Contribution Key column schema verified: 2026-04-08
