# Indiana (IN) campaign-finance jurisdiction package

## Jurisdiction overview
Indiana is a state-level jurisdiction (`fips: 18`) using Indiana Election Division (IED) bulk ZIP exports published in the Indiana Campaign Finance Online public portal.
The canonical ingest contract is annual yearly ZIP files for contributions and expenditures.

This package keeps machine-readable values in `config.yaml`. This README only documents access flow and verification status.
Stage 2 closeout aligns this package with the 2026-04-26 re-verdict: source advancement is weekly-or-better for launch support.

## Verification snapshot (2026-03-23)
- Entry page: `https://www.in.gov/sos/elections/campaign-finance/`
- Public portal root: `https://campaignfinance.in.gov/PublicSite/`
- Bulk-download page: `https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx`
- Portal page label: `FCPA Data Download`
- Portal as-of timestamp shown on page: `3/17/2026  1:00 AM`
- Verified available yearly links: 2000 through 2026 for both contributions and expenditures ZIP files.
- Machine-readable cadence in `config.yaml`: `weekly` for both configured data sources.

## Bulk-download access flow
1. Open `https://www.in.gov/sos/elections/campaign-finance/`.
2. Follow the `Indiana Campaign Finance Online` link to `https://campaignfinance.in.gov/` (redirects to `/PublicSite/`).
3. Open `Download Data` (`/PublicSite/Reporting/DataDownload.aspx`).
4. Click yearly links such as:
   - `https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip`
   - `https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ExpenditureData.csv.zip`

Retrieval behavior:
- The `DataDownload.aspx` page is an ASP.NET WebForms page and includes `__VIEWSTATE` and `__EVENTVALIDATION` fields.
- File retrieval itself is plain HTTP GET to static ZIP URLs (no postback replay required once URL is known).
- Source links are rendered with backslashes in HTML (`...BulkDataDownloads\2025_ContributionData.csv.zip`), but slash-normalized URLs work directly.

## Data sources summary
| Source | Pattern | Format | Cadence | Auth |
|---|---|---|---|---|
| IED Contributions | `{YEAR}_ContributionData.csv.zip` | ZIP containing one CSV | weekly | none |
| IED Expenditures | `{YEAR}_ExpenditureData.csv.zip` | ZIP containing one CSV | weekly | none |

Launch-readiness note: the portal keeps yearly ZIP URL templates but republishes them on a weekly-or-better cadence (`docs/reference/research/in_freshness_recheck_2026_04_26.md`).
Stage 2 baseline routing and disposition remain anchored by `docs/reference/research/in_mn_nj_freshness_stage1_baseline_2026_04_28.md`.

## Last verified date
- Portal access + download flow verified: 2026-03-23
- 2025 representative files downloaded and inspected: 2026-03-23
- Laws/guidance notes refreshed: 2026-03-23

## Update instructions
1. Re-open `DataDownload.aspx` and confirm newest available year links.
2. Download one contributions ZIP and one expenditures ZIP for the newest completed reporting year.
3. Re-check yearly URL templates and header order against `config.yaml` (machine-readable source of truth).
4. Refresh `data_semantics.md`, `laws.md`, and `sample_rows/` from those exact files.
5. Keep package wording aligned with the latest freshness evidence and update this README/config together when newer probes change the cadence verdict.
