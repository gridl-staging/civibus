<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | Virginia campaign finance scraper config helpers.

Loads config.yaml and provides typed accessors for data source blocks,
field mappings, and bulk download URLs. |
| cli.py | Virginia campaign finance CLI entry point.

Supports:
  --path <file>      Parse a local VA CSV file
  --download         Download from the VA SBE portal
  --data-type        contributions | expenditures
  --year-month       YYYY_MM for download mode (e.g. |
| download.py | Virginia campaign finance CSV downloader.

Downloads monthly CSV files from the VA SBE bulk export portal at
https://apps.elections.virginia.gov/SBE_CSV/CF/{year_month}/

The portal is organized by YYYY_MM directories containing:
  - ScheduleA.csv (contributions)
  - ScheduleD.csv (expenditures)
  - Report.csv (filing metadata)

No bot protection -- just needs a User-Agent header. |
| extract.py | Virginia campaign finance entity extraction.

Extracts Person, Organization, and Address entities from parsed VA CSV rows.
Uses the VA-specific IsIndividual field (string 'True'/'False') to decide
whether a row represents an individual or organization donor/payee.

Contribution rows (ScheduleA) produce donor entities.
Expenditure rows (ScheduleD) produce payee entities. |
| load.py | Virginia campaign finance DB loader.

Two-phase loading following the WI pattern:
  Phase 1: Source records + entity resolution (person/org/address)
  Phase 2: Filing upserts + transaction upserts (relational layer)

Uses try_row_without_savepoint to avoid exhausting max_locks_per_transaction
on large datasets. |
| parse.py | Virginia campaign finance CSV parser.

Parses ScheduleA (contributions), ScheduleD (expenditures), and Report CSVs
from the VA SBE bulk download. |
<!-- [scrai:end] -->
