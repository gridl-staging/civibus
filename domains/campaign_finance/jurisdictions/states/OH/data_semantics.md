# Ohio SOS campaign-finance data semantics

## Ownership and scope
This file is the Ohio-local evidence log.

- Keep machine-readable source metadata in `config.yaml` only.
- Keep operator workflow summary in `README.md` only.
- Keep live portal evidence, blocker timeline, source-shape notes, and unresolved hypotheses here.

Current project stance: Ohio is documented-and-deferred. Maintain the evidence log, but do not keep Ohio on the active launch critical path while easier states remain available.

## Checked-in contract seam (Stage 3 input to Stage 4)
Current behavior is defined by the checked-in downloader and CLI contract:

- `domains/campaign_finance/jurisdictions/states/OH/scraper/__init__.py::_load_bulk_download_url_for_data_type()` reads the listing template from `config.yaml`.
- `domains/campaign_finance/jurisdictions/states/OH/scraper/download.py::_scrape_apex_file_listing()` requests the APEX listing URL and raises upstream HTTP status failures via `response.raise_for_status()`.
- `domains/campaign_finance/jurisdictions/states/OH/scraper/download.py::download_oh_csv()` calls `_scrape_apex_file_listing()` first and then assumes the returned page contains direct static CSV links.
- `domains/campaign_finance/jurisdictions/states/OH/scraper/cli.py::run_oh_refresh()` in download mode propagates download failures from `download_oh_csv()`.

Contract tests that pin this seam:

- `test_scrape_apex_listing_classifies_403_as_upstream_http_failure`
- `test_download_oh_csv_propagates_listing_upstream_http_failure`
- `test_main_download_mode_reports_stage1_upstream_blocker`
- `test_run_oh_refresh_download_mode_propagates_stage1_upstream_blocker`

## Verified portal behavior timeline
- 2026-03-22: Ohio APEX file listing observed returning maintenance/blocked responses; live downloader verification deferred.
- 2026-03-23: repeated probes against CAN/PAC/PARTY listing URLs (curl, httpx, Playwright) all returned HTTP 403 with Cloudflare-backed maintenance response and no CSV links.
- 2026-03-24: broader probe matrix established that the portal is browser-session-sensitive, not just "down." Raw HTTP still returned `403`, headless automation still failed, but headed real Chrome could load the main search app and, in at least one successful session, the FTP page itself. The FTP page proved to be real and its download actions resolved through APEX page 72 `P72_GETID=...` links rather than static `*.CSV` URLs.

Current checked-in conclusion: the checked-in Ohio downloader is stale in two ways:

- it is blocked by the protected browser/session boundary when it tries to fetch page 73 directly with `httpx`,
- and it models the wrong downstream contract even after access is gained because the real FTP UI drives APEX page 72 download actions rather than exposing simple static CSV anchors.

## Source-shape inventory (evidence notes)
These details are non-structured evidence notes, not config fields:

- Transport model: browser-session-first access to the FTP listing page, followed by per-file APEX page 72 download actions.
- Data types: contributions and expenditures.
- Committee families on listing pages: `CAN`, `PAC`, `PARTY`.
- Titles seen live:
  - search app: `General Transaction Search - Ohio Secretary of State`
  - challenge/interstitial: `Ohio Secretary of State's Office Website Maintenance`, `Just a moment...`
  - FTP page: `New Files - File Transfer Page – Ohio Secretary of State`
- Challenge/session signals seen live:
  - Cloudflare-backed `403` responses under raw HTTP/headless probing
  - cookies such as `__cf_bm`, `cf_clearance`, and `ORA_WWV_APP_119`
- Real FTP page sections seen live:
  - `New Files`
  - `Candidate Files`
  - `PAC Files`
  - `Party Files`
- Real live download links observed from the FTP UI:
  - `https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:6509`
  - same page-72 pattern for additional file rows with different `P72_GETID` values
- Filename conventions observed in evidence set:
  - Contributions: `*_CON_YYYY.CSV` (`ALL_*` pre-2010 families and `CAC/PAC/PPC` post-2010 families).
  - Expenditures: `*_EXP_YYYY.CSV` (same family pattern shift).
- Date formats in rows are documented as `MM/DD/YYYY` for contribution and expenditure transaction dates.

Use `config.yaml` for canonical field mappings and structured metadata values.

## Unverified hypotheses and open questions
- Whether a persistent headed Chrome profile can make Ohio download automation reliable across repeated scheduled runs remains unverified.
- Whether the page 72 `P72_GETID` download flow can be replayed as plain HTTP after session bootstrap remains unverified.
- Whether browser-native download capture or request/response replay is the more durable extraction path remains unverified.
- Whether the maintenance response cadence changes around filing windows is unverified.
- Whether amendment semantics can be derived reliably from free-text report description fields remains unverified.

These are deferred questions, not current launch-critical tasks.

## External-risk status
Ohio should be treated as a protected browser-session-first source until a rewritten downloader proves otherwise. The current HTTP-first downloader should not be treated as the source of truth for portal behavior. The region is intentionally deferred for now: keep the evidence current, but prioritize easier weekly/daily states before spending more roadmap time on an Ohio rewrite. When new live evidence changes the observed challenge flow, FTP page structure, or page 72 download contract, update this file first, then adjust README wording and downloader expectations in the same change.
