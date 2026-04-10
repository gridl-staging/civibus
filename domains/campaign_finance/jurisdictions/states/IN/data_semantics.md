# Indiana IED campaign-finance data semantics

Observed from live Indiana IED downloads on 2026-03-23.

Portal workflow notes live in `README.md` (`Bulk-download access flow`). This file captures only raw-file behavior.
Machine-readable source cadence and implementation status live in `config.yaml`; this document does not define launch-readiness.

## Scope boundary
- Evidence here is limited to observed annual `{YEAR}_ContributionData.csv.zip` and `{YEAR}_ExpenditureData.csv.zip` exports.
- No supplementary API or higher-cadence official source is asserted in this file.
- Annual cadence remains freshness-limited for daily election coverage.

## Files inspected
Downloaded from:
- `https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip`
- `https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ExpenditureData.csv.zip`

Archive members:
- `2025_ContributionData.csv` (`22,191,129` bytes; ZIP member timestamp `2026-03-07 01:00` local in archive listing)
- `2025_ExpenditureData.csv` (`6,775,387` bytes; ZIP member timestamp `2026-03-07 01:00` local in archive listing)

## Delimiter, quoting, and encoding
- Delimiter: comma.
- Quoting: double-quoted CSV fields.
- Header width:
  - Contributions: 17 columns.
  - Expenditures: 18 columns.
- Encoding observations:
  - Both files contain non-ASCII bytes (`>= 0x80`).
  - Both fail strict UTF-8 decoding.
  - Expenditures decodes cleanly as `cp1252`; contributions contains byte `0x81` (undefined in `cp1252`) and decodes under `latin-1`.
  - Practical Stage 2 stance: treat source as legacy single-byte encoding and avoid UTF-8-only assumptions.

## Exact header rows
Contributions (`2025_ContributionData.csv`):
```text
"FileNumber","CommitteeType","Committee","CandidateName","ContributorType","Name","Address","City","State","Zip","Occupation","Type","Description","Amount","ContributionDate","Received_By","Amended"
```

Expenditures (`2025_ExpenditureData.csv`):
```text
"FileNumber","CommitteeType","Committee","CandidateName","ExpenditureCode","Name","Address","City","State","Zip","Occupation","OfficeSought","ExpenditureType","Description","Purpose","Amount","Expenditure_Date","Amended"
```

## Date literals
- Primary pattern in both files: `YYYY-MM-DD HH:MM:SS`.
- Most rows use midnight timestamp (`00:00:00`).
- Contributions include non-midnight timestamps in real data (examples observed for file `7966` such as `2025-08-28 16:24:45` and `2025-08-28 14:32:06`).

## Indiana code/value inventories (2025 sample year)
Contributions:
- `CommitteeType`: `Candidate`, `Legislative Caucus`, `Political Action`, `Regular Party`.
- `ContributorType`: `Individual`, `Other Organization`, `Corporation`, `Political Action Committee`, `Political Action`, `Labor Organization`, `Creditor`, `Recipient`, `Borrower`, blank.
- `Type`: `Direct`, `Unitemized`, `In-Kind`, `Interest`, `Loan`, `Misc`, `Debt - Debts Owed by this Committee`, `Debt - Debts Owed to this Committee`.
- `Amended`: mostly `0`, some `1`.

Expenditures:
- `CommitteeType`: `Candidate`, `Legislative Caucus`, `Political Action`, `Regular Party` (plus one malformed-row artifact value; see anomalies below).
- `ExpenditureCode`: `Advertising`, `Contributions`, `Fundraising`, `Loan Payment`, `Missing`, `Operations`, `Unitemized`, blank (malformed-row artifact).
- `ExpenditureType` includes combinations such as `Direct - Operations`, `Direct - Contributions`, `Unitemized - Unitemized`, `In-Kind - ...`, `Other - ...`, `Payment of Debt - ...`, `Returned Contribution - ...`.
- `Amended`: mostly `0`, some `1`.

## Native identifiers
- `FileNumber` is present in both datasets and appears filing-level (repeated across many transactions).
- No row-unique transaction identifier column was observed in either file.
- Candidate and committee naming is often text-only (`CandidateName`, `Committee`) with no stable person identifier.

## Null and sentinel conventions
- Primary null: empty string (`""`).
- Numeric amounts use decimal strings (for example `5000.0000`, `-300.0000`).
- `Amended` uses `0` and `1` in valid rows.
- `OfficeSought` is frequently blank in expenditures.

## Amendment/correction signals
- Both datasets expose `Amended` directly (`0`/`1`).
- 2025 examples show paired negative/positive adjustments with `Amended = 1` in both contributions and expenditures.

## Data-quality anomalies requiring parser safeguards
- Contributions: observed rows with unescaped double quotes in `Received_By` text (`Raymond ("Butch") L. Kramer, Jr.` in source), causing column-shift artifacts for strict CSV readers.
- Expenditures: observed rows where multiline description content includes raw quotes and line breaks (for example around `Ollie's ... 5'3" x 7'3" ...`), creating parse anomalies for strict row-oriented consumers.

## Open questions
1. Is there an official encoding declaration for yearly exports, or does encoding drift by filer/year? (2025 evidence indicates non-UTF8 single-byte data.)
2. Are malformed quoted rows fixed in later portal refreshes, or must parsing always include bad-row recovery logic?
3. Does `FileNumber` have a stable cross-form key relationship to filing metadata that can be joined without ambiguity?
