# New Jersey ELEC API data semantics

Observed from the ELEC e-filing search export API on 2026-03-26.

## Files and headers
- `contributions` export from the ELEC API contains row-level contribution facts with structured contributor name fields and employer information.
- The API returns a temporary Azure Blob URL; the blob hosts a standard CSV.

## CSV behavior
- Delimiter: comma.
- Quoting: standard CSV quoting.
- Field order: treated as contractually significant and validated by parser tests against config-derived columns.

## Semantics used in Stage 6 ingest
- Contributor identity: `IsIndividual` flag determines whether `FirstName`/`MI`/`LastName`/`Suffix` or `NonIndName` is the primary name field.
- Committee/recipient identity: `EntityName` is the receiving entity name.
- Transaction date and amount: `ContributionDate`, `ContributionAmount`.
- Contribution classification: `ContributionType`, `ContributorType`.
- Employer/occupation: `EmpName`, `OccupationName`.
- Election year: `ElectionYear`.
- Filing location: `Location` (filing jurisdiction).

## Known caveats
- The POST endpoint returns a JSON string, not a direct CSV stream.
- Blob URLs are temporary and expire; must download immediately after POST.
- `IsIndividual` is a string flag (observed values: "True"/"False").
