<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | NY scraper config helpers — loads field mappings and data source metadata from config.yaml. |
| cli.py | CLI for NY campaign finance pipeline — download from SODA API and load into DB.

Used by the refresh runner (run_ny_refresh) and manually via:
  python -m domains.campaign_finance.jurisdictions.states.NY.scraper.cli     --download --data-type contributions. |
| download.py | Download NY campaign finance data from the data.ny.gov SODA API.

Uses paginated CSV downloads with $limit/$offset. |
| extract.py | Extract Person, Organization, and Address entities from NY SODA rows.

NY contribution rows have donor entity fields (flng_ent_*) and committee
fields (cand_comm_name, filer_id). |
| load.py | Load NY campaign finance data into the database.

Two-pass loading (same pattern as WA):
1. |
| parse.py | Parse NY campaign finance CSV files downloaded from the SODA API.

Both contributions and expenditures share the same 45-column schema
(differentiated by filing_sched_abbrev). |
<!-- [scrai:end] -->
