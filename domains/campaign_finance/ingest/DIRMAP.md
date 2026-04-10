<!-- [scrai:start] -->
## ingest

| File | Summary |
| --- | --- |
| __init__.py | Federal campaign finance ingest package. |
| bulk_cli.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_cli.py. |
| bulk_loader.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_loader.py. |
| bulk_parser.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_parser.py. |
| bulk_stage4_loader.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_stage4_loader.py. |
| bulk_transaction_loader.py | Pure builders and lookups for FEC bulk transaction loading (Stage 2).

Consumes already-mapped contribution records from field_mapper.py.
Routes all cf.* writes through filing_loader.py.
Does not own raw-row parsing or direct SQL upserts. |
| cli.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/cli.py. |
| fec_canonical_loader.py | FEC canonical loader: maps FEC candidate-master rows into civic.* tables.

Reads the FEC cn (candidate master) bulk file, resolves or creates
core.person rows via the shared identity path, then maps each row into
canonical civic.office, civic.electoral_division, civic.contest, and
civic.candidacy using the shared upsert helpers from domains.civics.ingest.

The existing cf.candidate pipeline is NOT modified — this loader writes
only to civic.* tables. |
| fec_client.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/ingest/fec_client.py. |
| federal_officeholder_loader.py | Stub summary for federal_officeholder_loader.py. |
| field_mapper.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/field_mapper.py. |
| filing_loader.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/filing_loader.py. |
| loader.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/loader.py. |
| officeholder_contact.py | Shared officeholder contact-point helper for directory loaders. |
| schedule_e_loader.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_03_fec_schedule_e_independent_expenditures/civibus_dev/domains/campaign_finance/ingest/schedule_e_loader.py. |
| schedule_e_parser.py | Streaming CSV parser for FEC Schedule E (independent expenditures) bulk files.

Schedule E CSVs are comma-delimited UTF-8 with a header row — a different format
from the pipe-delimited headerless legacy bulk files parsed by bulk_parser.py.

Returns typed values: dates as datetime.date, amounts as Decimal, empty strings
as None. |

| Directory | Summary |
| --- | --- |
| dark_money | IRS 527 dark money data acquisition and processing module that downloads, parses, and loads independent political spending disclosures. |
<!-- [scrai:end] -->
