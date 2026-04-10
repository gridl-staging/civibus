<!-- [scrai:start] -->
## states

| File | Summary |
| --- | --- |
| __init__.py | State-level campaign finance jurisdiction modules. |
| config_helpers.py | Stub summary for config_helpers.py. |
| load_utils.py | Shared helpers for state campaign finance loaders. |

| Directory | Summary |
| --- | --- |
| AL | The Alabama campaign finance scraper downloads paginated JSON data from the FCPA portal (fcpa.alabamavotes.gov), with separate API endpoints for contributions and expenditures. |
| CA | The CA directory contains California's campaign finance data pipeline, implementing the full scraper workflow from configuration and parsing through extraction and loading of state-level disclosure data. |
| CO | Colorado campaign finance module implementing the standard domain plugin pipeline with download, parse, extract, and load stages for state campaign finance data acquisition. |
| FL | Florida campaign finance jurisdiction package with a scraper implementing the standard acquisition pipeline (download, parse, extract, load) and specialized loaders for candidacy records and officeholder-to-official mappings. |
| GA | Georgia campaign finance data scraper implementing the standard domain pipeline pattern with download, parse, extract, and load modules. |
| IL | The Illinois scraper directory contains the complete campaign finance data acquisition pipeline including download, parse, extract, and load modules with CLI entry points for managing state-level data operations. |
| IN | Indiana campaign finance scraper module for downloading, parsing, and extracting state disclosure data through a standard acquisition pipeline. |
| KY | Kentucky campaign finance scraper that downloads contributions and expenditures data via direct CSV export requests from the state's campaign finance endpoints. |
| LA | Louisiana campaign finance jurisdiction module with a standard data pipeline scraper that downloads raw files, parses them into structured records, and loads them into the database. |
| MA | The MA scraper pipeline downloads annual campaign finance data from OCPF Azure Blob Storage as ZIP files, extracts tab-delimited transaction records, and parses them for database ingestion. |
| MN | Minnesota campaign finance jurisdiction package implementing the standard state pipeline for downloading, parsing, extracting, and loading Minnesota campaign finance data from official sources. |
| NC | North Carolina campaign finance scraper implementing the standard data acquisition pipeline with download, parse, extract, and load stages. |
| NE | Nebraska campaign finance jurisdiction module containing a scraper pipeline that orchestrates CLI-driven download, parse, extract, and database load stages for state campaign finance data. |
| NJ | New Jersey campaign finance scraper that fetches contribution data from the NJ ELEC e-filing API via a two-step POST/GET workflow and provides CLI tools to parse and load the data into the pipeline. |
| NY | The NY scraper directory implements a complete ETL pipeline for downloading, parsing, and loading New York campaign finance data from the data.ny.gov SODA API, with modules for configuring the pipeline, extracting entity records (Person, Organization, Address), and performing two-pass database loading. |
| OH | The OH directory contains the Ohio campaign finance scraper implementation, including modules for downloading, parsing, and extracting entity data (persons, organizations, addresses) from Ohio's campaign finance portal, along with comprehensive unit and integration tests for the scraper pipeline. |
| OR | Oregon campaign finance scraper for ORESTAR using a session-based acquisition workflow that seeds a server session and exports XLS data via session cookie. |
| PA | Pennsylvania campaign finance jurisdiction package implementing a complete ETL scraper pipeline for downloading, extracting, parsing, and loading state campaign finance data into the database. |
| TX | The TX directory is the Texas campaign finance jurisdiction module containing a scraper pipeline that downloads source data, extracts and parses records, and loads them into the database via CLI operations. |
| VA | Virginia campaign finance scraper that downloads monthly CSV files from the Virginia State Board of Elections bulk export portal, parses contribution and expenditure schedules, extracts person/organization/address entities, and loads them into the database through two-phase entity resolution and transaction insertion workflows. |
| WA | The WA directory implements the Washington state campaign finance jurisdiction plugin, extracting contributions, expenditures, loans, independent expenditures, and officeholder records from state sources and transforming them into canonical civic entity tables and contact information. |
| WI | Wisconsin campaign finance scraper module implementing the standard state pipeline stages (download, parse, extract, load) with CLI entry point and config helpers, though most implementation files are currently stubbed. |
<!-- [scrai:end] -->
