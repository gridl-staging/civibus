# Illinois Campaign Finance

Official portal surfaces verified live on 2026-03-27:

- Division overview: `https://elections.il.gov/abouttheboard/DivCampaignDisclosure.aspx`
- Bulk download page: `https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx`
- Search pages:
  - `https://elections.il.gov/CampaignDisclosure/ContributionSearchByAllContributions.aspx`
  - `https://elections.il.gov/CampaignDisclosure/ExpenditureSearchByAllExpenditures.aspx`

## What Works

- The bulk download page is publicly reachable without login.
- The data-file dropdown triggers an ASP.NET postback on change; there is no separate submit button.
- After the postback, the page renders a `Download File` anchor pointing to `NewDocDisplay.aspx?...`.
- `Receipts.txt`, `Expenditures.txt`, and `CampaignDisclosureDataDictionary.txt` were all resolved live on 2026-03-27.
- The transaction files are tab-delimited text with header rows.

## Important URL Notes

- `https://elections.il.gov/CampaignDisclosure.aspx` returned an HTTP `302` redirect to `https://www.elections.il.gov` from this environment on 2026-03-27.
- `https://elections.il.gov/CampaignDisclosure/CampaignDisclosure.aspx` returned the generic error page (`"An error has occurred..."`) on 2026-03-27.
- Use the exact bulk download page URL above instead of guessing from the path prefix.

## Current Pipeline Scope

- The implemented pipeline ingests `Receipts.txt` as contributions.
- The implemented pipeline ingests `Expenditures.txt` as expenditures.
- The loader currently synthesizes committee display names from `CommitteeID` because those transaction files do not include committee names. `Committees.txt` remains the obvious next enrichment source.

## Session Requirements

- Production downloading does not require Playwright.
- The scraper uses `httpx` only:
  1. `GET` the download page to capture ASP.NET hidden fields
  2. `POST` the selected file name back to the same page
  3. Parse the rendered `Download File` link
  4. `GET` the resolved `NewDocDisplay.aspx?...` URL
- TLS verification is strict by default. Break-glass retry with certificate verification disabled requires both the CLI flag `--allow-insecure-tls` and `CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1`.

## Bounded Live Proof

- `--limit` only limits parse/load after a file exists locally.
- `--download-row-limit` is the bounded live-proof switch. It truncates the live stream on complete row boundaries and preserves a valid TSV sample from the official portal.
- Typical proof command:
  - `CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1 uv run python -m domains.campaign_finance.jurisdictions.states.IL.scraper.cli --download --data-type contributions --download-row-limit 25 --dry-run --allow-insecure-tls`
- Durable live-proof samples from 2026-03-27 are saved in `docs/research/artifacts/`.

## Known Limitations

- Official portal filing activity is now proven continuous via `ReportsFiled.aspx` (25 electronic filings across 2026-03-27 through 2026-03-29), but we still need direct evidence that bulk exports (`Receipts.txt`, `Expenditures.txt`) reflect those filings with same-day latency.
- Search pages were reachable, but no CSV/export controls were discovered from the server-rendered DOM on 2026-03-27.
- The transaction files are large full-history exports; the bounded proof path avoids blind waits, but full-history completion is still operationally heavier than proving the contract.
