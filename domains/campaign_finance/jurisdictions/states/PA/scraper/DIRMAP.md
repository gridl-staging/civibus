## PA Scraper Module Map

- `__init__.py`: Loads PA config metadata and resolves per-data-type field mappings and yearly download URLs.
- `download.py`: Streams the yearly PA archive to disk with atomic temp-file writes.
- `parse.py`: Selects `{type}_{year}.txt` members and parses rows with type-specific encodings (`cp437` or `utf-8`).
- `extract.py`: Maps parsed rows to typed committee/counterparty/address extraction objects.
- `load.py`: Loads source records and transactions with filing-level amendment inheritance via filer join.
- `load_support.py`: Shared PA loader helper functions extracted to keep `load.py` focused on orchestration paths.
- `cli.py`: Command-line entrypoint for `--year` ingest, download/path input selection, and dry-run row counting.

## Tests And Fixtures

- `test_fixtures/`: Representative PA fixture CSVs for contributions, expenditures, debts, receipts, and filings.
- `test_download.py`: Download URL routing, streaming write, and atomic temp-file behavior.
- `test_parse.py`: Header validation, malformed-row handling, encoding correctness, and ZIP-member selection rules.
- `test_extract.py`: Single-name person/org heuristics, committee extraction, and address normalization behavior.
- `test_load.py`: Source key and filing ID derivation, date parsing, amendment inheritance, and loader helper orchestration.
- `test_cli.py`: Argument parsing (`--year`, data types, mutually exclusive input modes), dry-run output, and main exit codes.
- `test_init.py`: Config-loading and mapping helper validations from Stage 3 scaffolding.
<!-- [scrai:start] -->
## scraper

| File | Summary |
| --- | --- |
| __init__.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/__init__.py. |
| cli.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/cli.py. |
| download.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/download.py. |
| extract.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/extract.py. |
| load.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/load.py. |
| load_support.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/load_support.py. |
| parse.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/parse.py. |
<!-- [scrai:end] -->
