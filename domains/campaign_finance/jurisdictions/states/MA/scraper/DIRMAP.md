<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | MA scraper config helpers — loads field mappings and data source metadata from config.yaml. |
| cli.py | CLI for MA campaign finance pipeline — download from OCPF and load into DB.

MA differs from other states: it downloads per-year ZIP files, extracts
report-items.txt, and loads them. |
| download.py | Download MA campaign finance data from OCPF Azure Blob Storage.

Downloads per-year ZIP files, extracts report-items.txt (tab-delimited
transaction data). |
| extract.py | Stub summary for extract.py. |
| load.py | Stub summary for load.py. |
| parse.py | Parse MA OCPF report-items.txt files (tab-delimited).

The report-items.txt file contains all transactions for a year —
contributions AND expenditures in one file. |
<!-- [scrai:end] -->
