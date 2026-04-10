<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | Ohio campaign finance scraper config helpers. |
| cli.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/cli.py. |
| download.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/download.py. |
| extract.py | Ohio campaign finance entity extraction.

Extracts Person, Organization, and Address entities from parsed OH CSV rows.
All column names are derived from config.yaml via _load_column_for_semantic_path()
— no hardcoded OH column names in this module.

OH-specific differences from TX:
- Entity/individual routing is implicit via NON_INDIVIDUAL field presence
  (no explicit type flag column like TX's contributorPersentTypeCd).
- OH has MIDDLE_NAME field — included in Person.middle_name and canonical_name.
- EMP_OCCUPATION (employer/occupation) is handled in load.py, not here
  (matching TX pattern where _counterparty_employer reads from the row directly). |
| load.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/load.py. |
| parse.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/parse.py. |
| probe.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_am_2_browser_audit_top_states/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/probe.py. |
<!-- [scrai:end] -->
