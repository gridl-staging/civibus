# Virginia (VA) — Data Semantics

## Source

Virginia Department of Elections (ELECT) monthly CSV bulk exports at
`https://apps.elections.virginia.gov/SBE_CSV/CF/`.

## Schedule mapping

| Schedule | Purpose | Transaction types |
|----------|---------|-------------------|
| A | Itemized monetary contributions | contributions |
| B | In-kind contributions | in_kind_contributions |
| C | Other receipts | receipts |
| D | Expenditures | expenditures |
| E | Loans | loans |
| F | Unpaid debts/obligations | debts |
| G | Summary totals (per-report) | summary |
| H | Balance sheet (per-report) | balance |
| I | Disposition of assets | dispositions |
| Report | Filing metadata (committee, dates, office) | filings |

## Key fields — ScheduleA (contributions)

- `ReportId` — links to Report.csv; identifies the filing this transaction belongs to
- `CommitteeContactId` — unique ID for the contributor within the VA system
- `FirstName`, `MiddleName`, `LastOrCompanyName` — contributor name (individual or organization)
- `IsIndividual` — string `"True"` or `"False"`; primary person-vs-org discriminator
- `NameOfEmployer`, `OccupationOrTypeOfBusiness` — employment info for individuals
- `TransactionDate` — date of contribution (mixed formats: `MM/DD/YYYY` and `YYYY-MM-DD HH:MM:SS`)
- `Amount` — contribution amount as decimal string
- `TotalToDate` — cumulative total from this contributor to this committee
- `ScheduleAId` — unique row ID for this contribution record
- `ReportUID` — GUID linking to the parent report

## Key fields — ScheduleD (expenditures)

- `ScheduleDId` — unique row ID for this expenditure
- `ReportId` — links to Report.csv
- `AuthorizingName` — name of person authorizing the expenditure
- `ItemOrService` — description of what was purchased

## Key fields — Report (filing metadata)

- `CommitteeCode` — official VA committee registration code (e.g., `CC-26-00123`)
- `CommitteeName` — official committee name
- `CommitteeType` — type classification (e.g., "Candidate Campaign Committee")
- `CandidateName` — candidate associated with committee (if applicable)
- `IsStateWide`, `IsGeneralAssembly`, `IsLocal` — office level flags (string True/False)
- `Party` — party affiliation
- `ElectionCycle` — cycle identifier (e.g., "3/2026")
- `OfficeSought`, `District` — office and district information
- `FilingType` — type of report (e.g., "Report", "Large Contribution Report")
- `IsAmendment` — whether this is an amendment to a previous filing
- `SubmittedDate` — when the report was submitted

## Date format

VA uses mixed date formats:
- `MM/DD/YYYY` in older records
- `YYYY-MM-DD HH:MM:SS.nnnnnnnnn` in newer records (nanosecond precision timestamps)

Parsers must handle both formats.

## Update cadence

Monthly CSV directories are regenerated daily (files timestamped at ~midnight ET).
Current month's directory contains filings received since the 1st of that month.
Historical directories contain full data for that month at time of generation.
