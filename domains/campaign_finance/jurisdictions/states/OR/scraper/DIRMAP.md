<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | OR scraper config helpers. |
| cli.py | Stub summary for cli.py. |
| download.py | Download helpers for OR campaign finance data.

ORESTAR uses a two-step session-based acquisition:
  Step 1: GET cneSearch.do with search params to seed the server-side session
  Step 2: GET XcelCNESearch with the session cookie to export XLS (tab-separated text). |
| extract.py | Entity extraction helpers for OR campaign finance rows.

ORESTAR names follow a "LAST FIRST" (space-separated) convention for individuals.
The "Addr Book Type" field distinguishes "Individual" from "Business Entity". |
| load.py | Stub summary for load.py. |
| parse.py | Stub summary for parse.py. |
<!-- [scrai:end] -->
