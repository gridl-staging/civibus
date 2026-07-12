# Minnesota campaign-finance data semantics

This document captures parsing assumptions for the Minnesota CSV exports. Machine-readable mapping authority remains in `config.yaml`.

## Shipped ingest boundary
- Stage 3 loader ingests contributions and expenditures from the quarterly direct-download `?download=` CSV feeds.
- Independent expenditures remain documented in config/docs only and are outside the shipped loader ingest path.
- Local campaign-finance reports are published on a separate board surface and remain outside this package's canonical ingest contract.

## Date fields
- MN contribution and expenditure rows use date strings in `YYYY-MM-DD` format in sampled files.
- Normalization target is ISO date (`YYYY-MM-DD`).
- Blank date cells normalize to null.

## Name formats
- Contributions use a single contributor field (`Contributor`) that may contain person-style values (`Last, First`) or organization names.
- Expenditures use `Vendor name` for payee identity.
- Committee names are carried directly from `Recipient` / `Committee name`.

## Employer/occupation
- Employer is available in contributions (`Contrib Employer name`).
- Occupation is not present in the MN CSV exports used in Stage 3.

## Address format
- Contributions provide ZIP-only donor address data (`Contrib zip`) in the sampled export.
- Expenditures provide `Vendor address 1`, `Vendor address 2`, `Vendor city`, `Vendor state`, and `Vendor zip`.
- Blank address components normalize to null.

## Committee IDs
- Contributions use `Recipient reg num` as committee identifier.
- Expenditures use `Committee reg num` as committee identifier.
- IDs are stored as strings and mapped to `mn_committee_reg_num` during extraction.

## Amendment handling
- Stage 3 MN exports do not include explicit amendment fields.
- Current ingestion treats rows as current-state records keyed by deterministic source-record hash.

## Missing/null conventions
- Empty CSV cells normalize to null.
- Malformed rows (short/long row width relative to header) are skipped and counted as quarantined parser rows.

## Portal Navigation
MN Stage 3 uses direct-download CSV URLs and does not require browser automation:
1. Entry page: `https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/`
2. Select export type and copy direct link using `?download=<id>`
3. Fetch CSV directly via HTTP and validate header order against `config.yaml`

## Stage 5 freshness source decision (2026-03-23)
Decision:
- No qualifying higher-frequency MN source is proven beyond the current quarterly `?download=` CSV contract as of 2026-03-23.
- The official `/reports/#/` search/export surface is date-filterable and API-backed, but current operator evidence only proves browser-session-backed access patterns and does not show fresher publication than quarterly download feeds.
- Treat `/reports/#/` as a supplemental query interface, not a replacement freshness source.
- `/reports/#/` and `/reports/api/` are supplemental evidence surfaces only and are not required for canonical ingest.
- Stage 3 closeout reaffirmed this as a resolved-negative freshness route via dated evidence:
  - `docs/reference/research/mn-freshness-investigation-2026-03-29.md`
  - `docs/reference/research/artifacts/2026-04-09-freshness-quality-probes/state-MN.json`
  - `docs/reference/research/in_mn_nj_freshness_stage1_baseline_2026_04_28.md`

Operator evidence captured:
- Official quarterly contract page with direct file downloads: `https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/`.
- Official data-usage/help page documenting the interactive reports/search surface: `https://register.cfb.mn.gov/citizen-resources/self-help/education-and-tools/exploring-and-using-board-data/`.
- Official reports UI surface: `https://register.cfb.mn.gov/reports/#/contributions-received/`.
- Stage 5 operator probing confirmed an API backend at `https://register.cfb.mn.gov/reports/api/` with `grid_info`, `grid_data`, and `searchbox` actions; direct no-session calls returned `403 Forbidden`, while session-backed requests returned report metadata/data.
- JavaScript application bundle showing reports client/API wiring: `https://register.cfb.mn.gov/cache/app.6f1bd146d8be9abaa8039903ea0535f2.js`.
- Official local campaign-finance reports are published as a separate surface, confirming boundary separation from the state-board contract: `https://register.cfb.mn.gov/reports-and-data/searches-and-lists/other-reports-and-lists/local-campaign-finance-reports/`.

Canonical limitation text:
- `MN /reports/#/ CSV export exists, but current operator evidence only proves session-backed access flows and has no proven fresher cadence than quarterly direct downloads.`

Open questions:
- Obtain board-published cadence evidence for `/reports/#/...` exports and API data refresh relative to quarterly `?download=` feeds.
