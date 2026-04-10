# Colorado TRACER Data Semantics

Field-by-field parsing and normalization rules based on actual 2025 CSV data inspection and the TRACER Download Data File Key (revised 07/2011).

## Date fields

- **Format**: `YYYY-MM-DD HH:MM:SS` (e.g., `2025-01-01 00:00:00`). Time component is always `00:00:00` — TRACER does not record sub-day precision.
- **Normalization**: Strip time component, output as `YYYY-MM-DD`.
- **Timezone**: Not specified in data. Assumed Mountain Time (America/Denver) based on jurisdiction.
- **Null handling**: Date fields may be blank for loans (PaymentDate blank on origination-only records).
- **Fields**: ContributionDate, FiledDate (contributions/expenditures); ExpenditureDate, FiledDate (expenditures); PaymentDate, FiledDate, LoanDate (loans).
- **Cross-year records**: The 2025 file contains records with ContributionDate in 2022, indicating late-filed or amended records can appear in a year file based on FiledDate, not transaction date.

## Name formats

- **Individual contributors**: Split across LastName, FirstName, MI, Suffix. All uppercase in source data.
- **Entity contributors**: Full entity name in LastName field; FirstName, MI, Suffix are blank.
- **Committee/candidate names**: CommitteeName and CandidateName are separate fields. CandidateName is populated only when a candidate record is linked to the committee.
- **LLC member names**: ContributorType field contains the LLC name embedded in the string (e.g., `Individual (Member of LLC: HOWES WOLF LLC)`). The individual member's name is in the standard name fields.
- **Normalization**: Title-case conversion recommended. Watch for suffixes like Jr., Sr., III, IV in the Suffix field.

## Employer/occupation

- **Contributions only**: Employer and Occupation fields are populated for contributions; documented as "not used" for expenditures (columns present but empty).
- **Occupation values**: Categorical (e.g., `Retired`, `Government/Civil`, `Clergy/Faith-based`) rather than free text.
- **OccupationComments**: Free-text field used when Occupation is `Other`. Only for individual donors.
- **Null strings**: Empty string (`""`) when not provided. No sentinel values observed.
- **Threshold**: Employer/occupation required only for contributions of $100+ from natural persons (Art. XXVIII § 7).
- **Blank rate**: ~9% of contribution records have empty ContributorType, likely corresponding to non-itemized or aggregate records where employer/occupation is not required.
- **Malformed rows**: 2025 ContributionData includes at least 14 rows where a donor first-name value contains broken quoting (`PERVAIZ 'PK",",",...`) and collapses CSV column alignment from 29 to 26 fields.

## Address format

- **Fields**: Address1 (street/PO Box), Address2 (suite/apt), City, State, Zip.
- **State abbreviation**: Standard 2-letter US postal abbreviation. Non-US addresses use country or province codes.
- **Zip format**: Mix of 5-digit (`80205`) and 9-digit (`80241-1234`) formats observed.
- **Missing components**: Address2 is frequently blank. Full address may be blank for non-itemized contributions.
- **All uppercase** in source data.

## Committee IDs

- **CO_ID format**: Alphanumeric string, typically 11 digits (e.g., `20155028940`). This is the SOS-assigned committee registration number.
- **Stability**: CO_ID is stable across years and file types. The same committee uses the same CO_ID in contribution, expenditure, and loan files.
- **Lookup**: CO_ID can be used to cross-reference committee details in the TRACER committee search.

## Amendment handling

- **Three fields**: Amended (Y/N), Amendment (Y/N), AmendedRecordID.
- **Amended = Y**: This record has been superseded by a newer amendment. The original record remains in the file.
- **Amendment = Y**: This record IS an amendment to a previously filed record. AmendedRecordID contains the RecordID of the original.
- **AmendedRecordID = 0**: Indicates no amendment relationship (default).
- **Resolution semantics**: To get current-state data, filter out records where `Amended = Y` (superseded originals). Records where `Amendment = Y` are the corrected versions and should be kept.
- **Observed rate**: In the 2025 file, the vast majority of records have `Amended = N, Amendment = N`, indicating low amendment frequency.

## Missing/null conventions

- **Empty string**: The primary null representation. Quoted empty string (`""`) in CSV.
- **Zero**: `AmendedRecordID = 0` means no amendment link (not a true zero ID).
- **Blank**: Explanation field is optional and frequently blank. OccupationComments is blank unless Occupation is `Other`.
- **No sentinel values**: No `-1`, `N/A`, `UNKNOWN`, or similar placeholders observed in the 2025 data. The string `Unknown` does appear as a ContributorType value (37 occurrences in 2025).
- **Row shape validation required**: Standard rows have 29 columns in contributions, 28 in expenditures, and 26 in loans. Quarantine rows that violate expected column counts before normalization.

## Portal Navigation

TRACER bulk download does not require portal navigation — files are direct HTTP downloads:

1. Entry URL: `https://tracer.sos.colorado.gov/PublicSite/DataDownload.aspx`
2. File URL pattern: `https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/{YEAR}_{DataType}Data.csv.zip`
   - DataType: `Contribution`, `Expenditure`, `Loan`
   - YEAR: `2000` through `2026` (verified range)
3. No authentication, session, or form interaction required.
4. Files are ZIP-compressed CSV. Each ZIP contains a single CSV file named `{YEAR}_{DataType}Data.csv`.
5. SSL certificate may require `-k` flag or custom CA bundle (observed `unable to verify the first certificate` in some environments).

## Observed ContributionType values

Core types: `Monetary (Itemized)`, `Monetary (Non-Itemized)`, `Non-Monetary (Itemized)`, `Non-Monetary (Non-Itemized)`, `Returned Contributions`, `Other Receipts`, `Non-Aggregated Receipts`, `NSF`, `Non-Monetary (Coordinated)`.

LLC variants embed the total LLC contribution amount: `Monetary (Itemized) - LLC Contribution (Total Amount: 500.00)`. These should be parsed to extract the base type and the LLC total amount separately.

## Observed CommitteeType values

`Candidate Committee`, `Political Party Committee`, `Political Committee`, `Small Donor Committee`, `Issue Committee`, `Federal PAC`, `Independent Expenditure Committee`, `527 Political Organization`.

## Observed ContributorType values

`Individual`, `Business`, `Corporation`, `Other`, `Candidate`, `Political Committee`, `Small Donor Committee`, `Political Party Committee`, `Federal PAC`, `Independent Expenditure Committee`, `Issue Committee`, `527 Political Organization`, `Labor Union`, `Partnership`, `Unknown`, `Candidate Committee`, `Political Party`.

LLC member variants: `Individual (Member of LLC: {LLC_NAME})`.
