# Florida (FL) campaign-finance jurisdiction package

## Jurisdiction overview
Florida is a state-level jurisdiction (`fips: 12`) using Florida Department of State CGI exports from `dos.elections.myflorida.com`.

This package keeps `config.yaml` as the machine-readable source of truth for endpoint URLs, field mappings, and coverage.

## Data sources summary
Florida publishes four campaign-finance export endpoints from query pages under `/campaign-finance/`.

| Source | Transaction type | Query page | POST target | Column count |
|---|---|---|---|---|
| FL DOS Campaign Finance - Contributions | contributions | `/campaign-finance/contributions/` | `/cgi-bin/contrib.exe` | 9 |
| FL DOS Campaign Finance - Expenditures | expenditures | `/campaign-finance/expenditures/` | `/cgi-bin/expend.exe` | 8 |
| FL DOS Campaign Finance - Transfers | transfers | `/campaign-finance/transfers/` | `/cgi-bin/FundXfers.exe` | 8 |
| FL DOS Campaign Finance - Other Disbursements | other | `/campaign-finance/other/` | `/cgi-bin/otherdis.exe` | 7 |

- Base site: `https://dos.elections.myflorida.com`
- Export format: tab-delimited text (TSV), CRLF line endings, US-ASCII
- Auth: none (but browser-like User-Agent is required)
- Update frequency: daily

## Officeholder directory sources (Stage 7)

Florida officeholder ingestion for Stage 7 uses official legislative directory pages:

- Senate roster landing page: `https://www.flsenate.gov/Senators/`
- Senator detail pages: `https://www.flsenate.gov/Senators/S27` (pattern)
- Operational cadence: weekly refresh minimum
- Required fields for canonical officeholding:
  - Holder identity: senator id slug, first/last name
  - Office + division: chamber + district number
  - Holder status: active/appointed/resigned/died (maps to elected/appointed/former)
  - Term window: term year range (e.g., `2024-2026`)
  - Office contacts: district and Tallahassee phones/addresses (`owner_type="office"`)

FL House source contract (documented, currently environment-blocked in this workspace):

- Directory page: `https://www.flhouse.gov/representatives`
- API surface observed: `https://www.flhouse.gov/api/document/house?...`
- Blocker status: repeated `Request Rejected` responses from this environment; browser-session capture in an unblocked environment is required for field-level extraction and vacancy semantics.

## Coverage notes
- `coverage.covers_sub_jurisdictions: true` because export rows include statewide and local committees/candidates.
- `coverage.start_year: 2000` is an operational lower bound for current pipeline assumptions and should be re-verified during first live backfill.

## Known quirks
- Browser-like User-Agent is required for stable access; default tool UAs can trigger Cloudflare 403.
- As of 2026-03-27, direct HTTP POST can still return Cloudflare-backed `502` HTML even after a successful landing-page GET; the downloader now falls back to a real browser-session form submission from the query page when that happens.
- Expenditures and transfers reject multi-day date ranges; those endpoints require day-by-day requests.
- Error payloads are returned as `HTTP 200 text/html`, not non-2xx status codes.
- Result sets truncate silently at `rowlimit`; high-volume windows must be partitioned.

## Verification status
- As of 2026-03-27, all four source types have current bounded live proof in this repo:
  - contributions: 499 loaded transactions / 117 linked filings
  - expenditures: 243 loaded transactions / 141 linked filings
  - transfers: 1 loaded transaction / 1 linked filing
  - other disbursements: 50 loaded transactions / 19 linked filings
- As of 2026-03-27, bounded `core.refresh.runner --job-key-prefix state-fl --force` proof also succeeded for all four `state-fl-*` jobs and updated source metadata with `last_pull_status=success`.
- As of 2026-03-28, retained `2024-07-10` Florida artifacts were loaded into the live production stack without disturbing the existing California slice. Production DB/API checks then confirmed `793` Florida transactions and `214` Florida filings were servable through the deployed stack.

## Update instructions
1. Re-check all four query pages and CGI POST targets for form parameter or header changes.
2. Re-run `make validate-configs` and FL scraper tests after any config or parser updates.
3. If headers or endpoint behavior change, update `config.yaml`, `data_semantics.md`, and this README in the same change.
