<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | KY scraper config helpers. |
| cli.py | Stub summary for cli.py. |
| download.py | Download helpers for KY campaign finance data.

Kentucky exposes separate public CSV export endpoints for transaction search
results:

- contributions: ``/ExportContributors``
- expenditures: ``/Export``

Both export contracts are direct GET requests and do not require a browser
session once the correct query-string parameters are supplied. |
| extract.py | Stub summary for extract.py. |
| load.py | Stub summary for load.py. |
| parse.py | Stub summary for parse.py. |
<!-- [scrai:end] -->
