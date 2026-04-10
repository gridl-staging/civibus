<!-- [scrai:start] -->
## cities

| File | Summary |
| --- | --- |

| Directory | Summary |
| --- | --- |
| LA | LA city campaign-finance scraper module with a two-pass loader (load.py) handling provenance tracking and relational data insertion, while download, parse, and cli pipeline stages remain stubbed out. |
| NYC | NYC campaign finance scraper that downloads bulk CSV data directly from the Campaign Finance Board and loads it into the database using a two-pass approach that tracks provenance separately before inserting relational data. |
| SF | The SF scraper implements the campaign finance acquisition pipeline for San Francisco, with modules for downloading data from the SF Ethics Commission portal, parsing filings, extracting structured records, loading into the database, and providing CLI orchestration commands. |
<!-- [scrai:end] -->
