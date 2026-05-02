# Georgia Campaign Finance (GA)

## Jurisdiction overview

This package defines Georgia state campaign-finance portal configuration under `domains/campaign_finance/jurisdictions/states/GA/`.

The jurisdiction is statewide (`GA`, FIPS `13`) and includes records for both state-level contests and sub-jurisdiction contests (county and municipal offices) observed in portal search surfaces.

Machine-readable source behavior, mappings, and legal settings are in `config.yaml`.

## Data sources summary

Georgia campaign-finance data is currently scrape-only from the Georgia Government Transparency and Campaign Finance Commission public portal (`media.ethics.ga.gov`).

Configured sources:

- Contributions search export (`Campaign_ByContributions.aspx`): `format: "web_portal"`, anonymous access, stateful ASP.NET workflow, export attachment `StateEthicsReport.csv`.
- Expenditures search export (`Campaign_ByExpenditures.aspx`): `format: "web_portal"`, anonymous access, stateful ASP.NET workflow, export attachment `EthicsReportExport.xls` (HTML-table payload).
- Independent expenditures search export (`Campaign_ByIEFiler.aspx`): configured as a tracked portal surface, but the URL returned HTTP 404 during the 2026-04-29 recheck so it remains documented-but-unproven.

No official bulk-download URL or API base URL was found on campaign search surfaces during verification, so both are explicitly `null` in `config.yaml` for all three tracked portal surfaces.

## Coverage notes

Observed search and export behavior indicates:

- Earliest reachable filing-year coverage is at least 2000.
- Coverage includes sub-jurisdictions (`covers_sub_jurisdictions: true`) based on observed county and municipal office surfaces/results.
- Transaction coverage includes contributions, loans (via the contribution search export `Type` field), and expenditures in this stage; additional transaction classes may require separate portal flows.
- Independent expenditures are modeled as a separate portal surface, but the currently configured IE URL is still deferred pending recovery from the observed 2026-04-29 HTTP 404.

## Portal constraints and access behavior

The portal is ASP.NET postback-driven and requires a single continuous browser context per scrape run.

Operational constraints:

- Preserve `ASP.NET_SessionId` plus hidden form state (`__VIEWSTATE`, `__EVENTVALIDATION`) through search, pagination, and export.
- Keep low-rate, single-session scrape behavior.
- Contribution export returns the full matching result set rather than only the currently visible page.
- Raw HTTP-only replay is less reliable for complex postback chains than browser automation preserving state.

## Known data quality issues

- Contribution export may be saved locally with `.xls` extension by clients even when payload is CSV.
- Expenditure export advertises `.xls` but payload is an HTML table, not a binary Excel workbook.
- Missing values are represented inconsistently across exports (empty CSV fields vs HTML non-breaking spaces).
- All records are loaded with `amendment_indicator='N'` because the portal export lacks amendment flags; see `data_semantics.md` for resolution semantics.

See `data_semantics.md` and `config.yaml` `known_issues` for field-level normalization and scraper-handling details.

## Last verified date

Source access and portal workflow verified: 2026-03-26.
Independent expenditures surface re-check: 2026-04-29 (HTTP 404 at `Campaign_ByIEFiler.aspx`).
Laws research verified: 2026-03-14.

## Update instructions

Re-verify by running a one-page contribution search, then paginate once and trigger export in the same browser context to confirm hidden-state continuity and export behavior. Re-check the IE URL separately until the HTTP 404 is resolved.

Recommended refresh steps:

1. Validate both contribution and expenditure entry URLs still resolve.
2. Confirm search -> results -> export workflow still works with a single ASP.NET session.
3. Re-download representative exports and compare headers against `field_mappings` in `config.yaml`.
4. Re-check legal citations in `laws.md` and update `laws.last_verified` if statutory or commission guidance changed.
