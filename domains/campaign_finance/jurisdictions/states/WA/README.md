# Washington (WA) campaign-finance jurisdiction package

## Jurisdiction overview
Washington is a state-level jurisdiction (`fips: 53`) using Washington Public Disclosure Commission (PDC) Socrata datasets exposed through `data.wa.gov` CSV/API endpoints.

This package keeps `config.yaml` as the only machine-readable source of truth for dataset IDs, API URLs, coverage, and field mappings.

## Data sources summary
WA PDC publishes four source-available campaign-finance datasets via Socrata resources:

| Source | Transaction type | Ingest support |
|---|---|---|
| WA PDC Contributions | contributions | Ingest-supported |
| WA PDC Expenditures | expenditures | Ingest-supported |
| WA PDC Independent Expenditures | independent_expenditures | Ingest-supported |
| WA PDC Loans | loans | Ingest-supported |

- Landing page: `https://www.pdc.wa.gov/political-disclosure-reporting-data/open-data`
- API base: `https://data.wa.gov/resource`
- Format: API-backed CSV
- Auth: none
- Update frequency: daily
- WA PDC Independent Expenditures follows the same WA filing + transaction ingest path as contributions, expenditures, and loans.
- Dataset IDs are authoritative in config.yaml.

## Officeholder directory source (Stage 7)

WA officeholder ingestion uses the official legislative sponsor directory feed:

- Contract page: `https://wslwebservices.leg.wa.gov/SponsorService.asmx?op=GetSponsors`
- Runtime endpoint: `https://wslwebservices.leg.wa.gov/SponsorService.asmx/GetSponsors?biennium=2025-26`
- Format: XML web service
- Auth: none
- Operational cadence: weekly refresh minimum (endpoint updates intra-biennium)

Required holder/contact fields from the feed:

- Holder identity: `Id`, `FirstName`, `LastName`, `Name`, `LongName`
- Office + division: `Agency` (`House`/`Senate`), `District`
- Holder status + term assumptions: current feed row implies active holder for current biennium (vacancy if `Name`/`Id` is blank or marked vacant)
- Contact ownership split:
  - Institutional office contact: `Phone` -> `owner_type="office"`
  - Personal official contact: `Email` -> `owner_type="officeholding"`

## Coverage notes
`coverage.covers_sub_jurisdictions` remains `true` for all WA sources.

Dataset schemas include jurisdiction fields (`jurisdiction`, `jurisdiction_county`, `jurisdiction_type`) and cover both state and local reporting surfaces.

## Known data quality issues
- WA metadata text and API-observed minima can diverge due rolling-window behavior; treat `coverage.start_year` as operationally re-verifiable.
- Loans dataset drift note: g6x6-jd8p -> d2ig-r3q4.
- Dataset release metadata includes a non-commercial reuse condition citing RCW 42.56.070(9) and AGO 1975 No. 15.

## Last verified date
- Contributions, expenditures, and loans live proof plus bounded runner-path proof verified: 2026-03-27
- Contributions, expenditures, and loans additive production proof verified: 2026-03-28
  - Production DB/API evidence: 500 contribution source records, 500 expenditure source records, 500 loan source records, 1,500 transactions, 613 filings
- Independent expenditures source-available contract re-verified: 2026-03-25
- Laws/restriction notes verified: 2026-03-21

## Update instructions
1. Re-check PDC open-data metadata and confirm ingest support boundaries still match current code.
2. Verify CSV headers still match `config.yaml` field mapping order.
3. Re-run `make validate-configs` and WA scraper tests.
4. If any dataset ID changes, update `config.yaml` and ensure this README still summarizes ingest scope correctly.
