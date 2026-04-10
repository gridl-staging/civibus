# Texas campaign-finance law notes

This file is narrative support for the TX `laws` block in `config.yaml`.

## Authoritative source
- TX Election Code Title 15 (campaign finance regulation): `https://www.ethics.state.tx.us/laws/election-code/`
- TX Election Code Chapter 253 (prohibitions on contributions): `https://statutes.capitol.texas.gov/Docs/EL/htm/EL.253.htm`
- TX Election Code Chapter 254 (reporting requirements): `https://statutes.capitol.texas.gov/Docs/EL/htm/EL.254.htm`
- Texas Ethics Commission adopted rule §18.31 (adjusted reporting thresholds effective January 1, 2026): `https://www.ethics.state.tx.us/rules/adopted/2021-2025/adopted_Sep_2025.php`
- TEC campaign finance search portal: `https://www.ethics.state.tx.us/search/cf/`

## Contribution limits table
- Texas has no contribution limits for individuals, PACs, or parties to candidates.
- Direct corporate and union contributions to candidates are prohibited (Chapter 253).
- Corporate and union PAC contributions are permitted.

## Itemization threshold
- Texas does not use one flat threshold across all Chapter 254 reports.
- Under Texas Ethics Commission Rule §18.31, effective January 1, 2026, the adjusted Chapter 254 thresholds are $110 for contributions and loans and $230 for expenditures.
- `config.yaml` keeps `itemization_threshold: 110` as the lowest current disclosure threshold and documents the higher expenditure threshold in notes.

## Reporting periods and deadlines
- Semi-annual reports (January 15 and July 15).
- Opposed-candidate pre-election reports are due on the 30th day and the 8th day before election day.
- Opposed-candidate runoff reports are due by the 8th day before runoff election day and cover activity through the 10th day before the runoff.
- Most TEC filers must file electronically unless they qualify for a statutory exemption; under Texas Ethics Commission Rule §18.31, effective January 1, 2026, the exemption ceiling is $34,890 in calendar-year contributions and expenditures, and the filer must also avoid computerized recordkeeping.

## Public financing
- No Texas public-financing scheme is modeled in this package (`public_financing: false`).

## Amendment handling
- `infoOnlyFlag` in transaction rows indicates superseded data (`Y` = superseded by later report).
- `formTypeCd` starting with `COR` indicates correction affidavits.
- Mapping to `AmendmentIndicatorLiteral`: `A` for corrections, `T` for superseded, `N` otherwise.

## Known ambiguities
- `infoOnlyFlag='Y'` clearly marks superseded rows, but downstream loader behavior (map to `T` vs. skip entirely) should be confirmed during implementation.
- TEC archive includes both state and local filings without a clear jurisdiction-level separation field.
