<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | AL scraper config helpers. |
| cli.py | Stub summary for cli.py. |
| download.py | Download helpers for AL campaign finance data from the FCPA JSON API.

The FCPA portal at fcpa.alabamavotes.gov provides a paginated JSON search API.
Contributions use the contributionsearchresults page; expenditures use
expendituresearchresults. |
| extract.py | Entity extraction helpers for AL rows.

Extracts Person, Organization, and Address entities from normalized
AL FCPA JSON rows, following the same patterns as NE extract.py. |
| load.py | Stub summary for load.py. |
| parse.py | Stub summary for parse.py. |
<!-- [scrai:end] -->
