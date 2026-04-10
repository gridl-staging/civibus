<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | Stub summary for WA scraper config helpers. |
| cli.py | Stub summary for cli.py. |
| download.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/WA/scraper/download.py. |
| extract.py | Stub summary for extract.py. |
| load.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/WA/scraper/load.py. |
| load_support.py | Stub summary for load_support.py. |
| parse.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/WA/scraper/parse.py. |
| wa_canonical_loader.py | WA canonical loader: maps WA PDC rows into civic.* tables.

Reads WA contribution, expenditure, loan, and independent-expenditure rows
(dict format from CSV/API) and maps candidate information into canonical
civic.office, civic.electoral_division, civic.contest, and civic.candidacy
using the shared upsert helpers from domains.civics.ingest.

IE rows additionally extract sponsor_email/sponsor_phone into core.contact_point.

The existing cf.* pipeline is NOT modified — this loader writes only to
civic.* + core.contact_point. |
| wa_officeholder_loader.py | WA officeholder loader: maps GetSponsors XML rows into civic.officeholding.

Separate from the WA candidate loader (wa_canonical_loader.py) which writes
candidacy records. |
<!-- [scrai:end] -->
