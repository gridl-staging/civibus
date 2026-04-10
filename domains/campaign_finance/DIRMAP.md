<!-- [scrai:start] -->
## campaign_finance

| File | Summary |
| --- | --- |
| validate_configs.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/validate_configs.py. |

| Directory | Summary |
| --- | --- |
| coverage | The coverage directory manages jurisdiction planning and registry infrastructure for campaign finance data collection, with a master CSV generator as the primary artifact that enriches jurisdiction metadata with population and election dates for strategic planning. |
| entity_extractors | Entity extractors for the campaign finance domain, providing FEC donor name parsing utilities that handle the standard LAST, FIRST MIDDLE SUFFIX format. |
| ingest | This directory contains the federal campaign finance data ingestion pipeline, with loaders and parsers for FEC bulk files (contributions, candidates, officeholders, Schedule E independent expenditures) and dark money data from IRS 527 organizations. |
| jurisdictions | The jurisdictions directory houses campaign finance acquisition modules organized into states (25+ state-level scrapers) and cities (independent local disclosure portals for LA, NYC, SF), each implementing downloaders, parsers, and loaders that integrate jurisdiction-specific sources into the core data pipeline. |
| normalize | The normalize directory contains utilities for standardizing campaign finance data types: addresses, dates, and names. |
| quality | Campaign finance data quality checks and reconciliation framework that orchestrates anomaly detection, validates data freshness, and generates closeout evidence artifacts for federal (FEC) and state sources. |
| tests | The tests directory contains integration and end-to-end test modules covering database operations, graph queries, relational queries, and stage-specific validation across campaign finance and infrastructure components. |
| types | The types directory exports campaign-finance data models, with primary focus on dark money entities via the dark_money_models.py module which defines IRS 527 political organization and filing records (Forms 8871/8872) parsed from pipe-delimited bulk files, normalizing field names to snake_case. |
<!-- [scrai:end] -->
