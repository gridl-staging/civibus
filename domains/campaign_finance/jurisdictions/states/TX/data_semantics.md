# Texas TEC campaign-finance data semantics

Observed from live archive download on 2026-03-21:
- Archive URL: `https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip`
- Format: ZIP (`content-type: application/zip`)
- Size: `1,009,895,194` bytes (`content-length`)
- Members: 135 files. Full per-file row-count/delimiter inventory: `sample_rows/member_inventory.tsv`
- Per-file UTF-8 validation: `sample_rows/encoding_check.tsv` (`yes` for all 135 members)

## Date fields
- TX README inside archive (`CFS-ReadMe.txt`) declares TEC date masks as `yyyyMMdd` for campaign rows.
- Contributions and expenditures use `receivedDt` + transaction date (`contributionDt` / `expendDt`) in `YYYYMMDD` (8 digits).
- Loans use `receivedDt`, `loanDt`, and optional `maturityDt` in `YYYYMMDD`; blanks are observed for optional loan dates.
- Quoting is selective rather than all-or-nothing: many text cells are double-quoted, while dates, amounts, flags, and some plain-text cells are emitted without quotes.
- No timezone is included in source rows.

## Name formats
- Record-level person/entity mode is explicit via `*PersentTypeCd` fields (for example `contributorPersentTypeCd`, `payeePersentTypeCd`, `lenderPersentTypeCd`).
- Entity names use `*NameOrganization`; individual names use split columns (`*NameLast`, `*NameFirst`, `*NameSuffixCd`, `*NamePrefixCd`, `*NameShort`).
- Person/entity naming layout is consistent across contribution, expenditure, and loan rows.

## Employer/occupation
- Contributions include `contributorEmployer`, `contributorOccupation`, `contributorJobTitle`.
- Loans include `lenderEmployer`, `lenderOccupation`, `lenderJobTitle` (and analogous guarantor fields).
- Expenditures do not include payee employer/occupation fields.
- Empty string cells are common for optional employment fields.

## Address format
- Contribution rows include contributor city/state/country/postal via `contributorStreetCity`, `contributorStreetStateCd`, `contributorStreetCountryCd`, `contributorStreetPostalCode`, `contributorStreetRegion` (no street-line columns in contribution rows).
- Expenditure rows include street-line fields: `payeeStreetAddr1`, `payeeStreetAddr2`, then city/state/country/postal/region.
- Loan rows include lender city/state/country/postal/region and analogous guarantor address blocks.

## Committee IDs
- Native filer/committee identifier: `filerIdent`.
- Native filing/report identifier: `reportInfoIdent` (re-used across many transaction rows in the same filing).
- Native transaction identifiers are file-type specific and unique within sampled files:
  - Contributions: `contributionInfoId`
  - Expenditures: `expendInfoId`
  - Loans: `loanInfoId`

Mapping decisions:
- `source_record_key`
  - Contributions: `contributionInfoId`
  - Expenditures: `expendInfoId`
  - Loans: `loanInfoId`
  - Fallback: deterministic row hash only for TX member files without a transaction-id column.
- `transaction_identifier`
  - Same native transaction-id field as `source_record_key` for each transaction type.
- `filing_fec_id`
  - `TX-{filerIdent}-{receivedDt[0:4]}-{data_type}`

## Amendment handling
Observed amendment-adjacent fields:
- `infoOnlyFlag` in transaction rows (`N` and `Y` observed). README defines it as "Superseded by other report".
- `formTypeCd` includes correction affidavit codes (`CORCOH`, etc.) from archive `CFS-Codes.txt`.

Mapping decision for `AmendmentIndicatorLiteral`:
- `A`: `formTypeCd` starts with `COR`
- `T`: `infoOnlyFlag == "Y"` (superseded by later report)
- `N`: otherwise

## Missing/null conventions
- Primary null representation is an empty CSV field (`,,`).
- Optional dates (for example some `expendDt`, `maturityDt`) can be blank.
- Boolean/flag fields are coded as `Y`/`N`.
- Enumerated unknowns appear as literals such as `UNKNOWN` in some category/status fields.

## Portal Navigation
TX TEC bulk data is direct-download; no browser automation is required.
1. Entry/search page: `https://www.ethics.state.tx.us/search/cf/index.php`
2. Bulk ZIP link exposed on that page: `https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip`
3. Download and inspect ZIP members.

## Exact header rows (required transaction CSV types)
Contributions (`contribs_##.csv`, identical header across all `contribs_*.csv` members):
```text
recordType,formTypeCd,schedFormTypeCd,reportInfoIdent,receivedDt,infoOnlyFlag,filerIdent,filerTypeCd,filerName,contributionInfoId,contributionDt,contributionAmount,contributionDescr,itemizeFlag,travelFlag,contributorPersentTypeCd,contributorNameOrganization,contributorNameLast,contributorNameSuffixCd,contributorNameFirst,contributorNamePrefixCd,contributorNameShort,contributorStreetCity,contributorStreetStateCd,contributorStreetCountyCd,contributorStreetCountryCd,contributorStreetPostalCode,contributorStreetRegion,contributorEmployer,contributorOccupation,contributorJobTitle,contributorPacFein,contributorOosPacFlag,contributorLawFirmName,contributorSpouseLawFirmName,contributorParent1LawFirmName,contributorParent2LawFirmName
```

Expenditures (`expend_##.csv`, identical header across all `expend_*.csv` members):
```text
recordType,formTypeCd,schedFormTypeCd,reportInfoIdent,receivedDt,infoOnlyFlag,filerIdent,filerTypeCd,filerName,expendInfoId,expendDt,expendAmount,expendDescr,expendCatCd,expendCatDescr,itemizeFlag,travelFlag,politicalExpendCd,reimburseIntendedFlag,srcCorpContribFlag,capitalLivingexpFlag,payeePersentTypeCd,payeeNameOrganization,payeeNameLast,payeeNameSuffixCd,payeeNameFirst,payeeNamePrefixCd,payeeNameShort,payeeStreetAddr1,payeeStreetAddr2,payeeStreetCity,payeeStreetStateCd,payeeStreetCountyCd,payeeStreetCountryCd,payeeStreetPostalCode,payeeStreetRegion,creditCardIssuer,repaymentDt
```

Loans (`loans.csv`):
```text
recordType,formTypeCd,schedFormTypeCd,reportInfoIdent,receivedDt,infoOnlyFlag,filerIdent,filerTypeCd,filerName,loanInfoId,loanDt,loanAmount,loanDescr,interestRate,maturityDt,collateralFlag,collateralDescr,loanStatusCd,paymentMadeFlag,paymentAmount,paymentSource,loanGuaranteedFlag,financialInstitutionFlag,loanGuaranteeAmount,lenderPersentTypeCd,lenderNameOrganization,lenderNameLast,lenderNameSuffixCd,lenderNameFirst,lenderNamePrefixCd,lenderNameShort,lenderStreetCity,lenderStreetStateCd,lenderStreetCountyCd,lenderStreetCountryCd,lenderStreetPostalCode,lenderStreetRegion,lenderEmployer,lenderOccupation,lenderJobTitle,lenderPacFein,lenderOosPacFlag,lenderLawFirmName,lenderSpouseLawFirmName,lenderParent1LawFirmName,lenderParent2LawFirmName,guarantorPersentTypeCd1,guarantorNameOrganization1,guarantorNameLast1,guarantorNameSuffixCd1,guarantorNameFirst1,guarantorNamePrefixCd1,guarantorNameShort1,guarantorStreetCity1,guarantorStreetStateCd1,guarantorStreetCountyCd1,guarantorStreetCountryCd1,guarantorStreetPostalCode1,guarantorStreetRegion1,guarantorEmployer1,guarantorOccupation1,guarantorJobTitle1,guarantorLawFirmName1,guarantorSpouseLawFirmName1,guarantorParent1LawFirmName1,guarantorParent2LawFirmName1,guarantorPersentTypeCd2,guarantorNameOrganization2,guarantorNameLast2,guarantorNameSuffixCd2,guarantorNameFirst2,guarantorNamePrefixCd2,guarantorNameShort2,guarantorStreetCity2,guarantorStreetStateCd2,guarantorStreetCountyCd2,guarantorStreetCountryCd2,guarantorStreetPostalCode2,guarantorStreetRegion2,guarantorEmployer2,guarantorOccupation2,guarantorJobTitle2,guarantorLawFirmName2,guarantorSpouseLawFirmName2,guarantorParent1LawFirmName2,guarantorParent2LawFirmName2,guarantorPersentTypeCd3,guarantorNameOrganization3,guarantorNameLast3,guarantorNameSuffixCd3,guarantorNameFirst3,guarantorNamePrefixCd3,guarantorNameShort3,guarantorStreetCity3,guarantorStreetStateCd3,guarantorStreetCountyCd3,guarantorStreetCountryCd3,guarantorStreetPostalCode3,guarantorStreetRegion3,guarantorEmployer3,guarantorOccupation3,guarantorJobTitle3,guarantorLawFirmName3,guarantorSpouseLawFirmName3,guarantorParent1LawFirmName3,guarantorParent2LawFirmName3,guarantorPersentTypeCd4,guarantorNameOrganization4,guarantorNameLast4,guarantorNameSuffixCd4,guarantorNameFirst4,guarantorNamePrefixCd4,guarantorNameShort4,guarantorStreetCity4,guarantorStreetStateCd4,guarantorStreetCountyCd4,guarantorStreetCountryCd4,guarantorStreetPostalCode4,guarantorStreetRegion4,guarantorEmployer4,guarantorOccupation4,guarantorJobTitle4,guarantorLawFirmName4,guarantorSpouseLawFirmName4,guarantorParent1LawFirmName4,guarantorParent2LawFirmName4,guarantorPersentTypeCd5,guarantorNameOrganization5,guarantorNameLast5,guarantorNameSuffixCd5,guarantorNameFirst5,guarantorNamePrefixCd5,guarantorNameShort5,guarantorStreetCity5,guarantorStreetStateCd5,guarantorStreetCountyCd5,guarantorStreetCountryCd5,guarantorStreetPostalCode5,guarantorStreetRegion5,guarantorEmployer5,guarantorOccupation5,guarantorJobTitle5,guarantorLawFirmName5,guarantorSpouseLawFirmName5,guarantorParent1LawFirmName5,guarantorParent2LawFirmName5
```

## Open questions
- `infoOnlyFlag == "Y"` clearly marks superseded rows, but downstream loaders may choose either to map them to `T` or to quarantine/skip them entirely. This doc records the literal mapping decision above; loader behavior should be confirmed in implementation stage.
