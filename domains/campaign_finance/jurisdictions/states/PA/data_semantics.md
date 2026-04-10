# Pennsylvania DOS campaign-finance data semantics

Observed from live PA DOS campaign-finance export portal on 2026-03-21.
Primary page: `https://www.pa.gov/agencies/dos/resources/voting-and-elections-resources/campaign-finance-data`

Downloaded archive:
- URL: `https://www.pa.gov/content/dam/copapwp-pagov/en/dos/resources/voting-and-elections/campaign-finance/campaign-finance-data/2025%20campaign%20finance%20full%20export%20.zip`
- Format: ZIP
- Size: `26,638,457` bytes
- Members: 5 files (full inventory with row counts: `sample_rows/member_inventory.tsv`)
- Per-file encoding evidence: `sample_rows/encoding_check.tsv`
  - UTF-8 valid: `debt_2025.txt`, `filer_2025.txt`, `receipt_2025.txt`
  - Non-UTF8 files: `contrib_2025.txt`, `expense_2025.txt`
  - Byte-level evidence in non-UTF8 files includes `0x82` (and `0xA0`, `0xFF` in `contrib_2025.txt`), which decodes correctly under DOS code pages (`cp437`/`cp850`) for observed names such as `Café`, `José`, and `González`, but decodes incorrectly under `cp1252` (`Caf‚`, `Jos‚`, `Gonz lez`).
  - Parsing decision for implementation stages: decode non-UTF8 PA files with `cp437` (`cp850` is equivalent for the observed byte set).

## Date fields
- `SubmittedDate` uses `YYYY-MM-DD` across all 5 member files.
- Transaction/date columns in detail files use `YYYYMMDD`:
  - Contributions: `CONTDATE1` (plus `CONTDATE2`, `CONTDATE3` sentinel fields)
  - Expenses: `EXPDATE`
  - Debt: `DBTDATE`
  - Receipts: `RECDATE`
- Contributions use sentinel zeros in secondary/tertiary date/amount slots (`CONTDATE2/3`, `CONTAMT2/3`), with observed values of `0` or `0.00` when unused.
- Quoting is mixed: many text fields are double-quoted, numeric fields are commonly unquoted, and unused text columns can appear as `""`.

## Name formats
- Contributions use single contributor field: `CONTRIBUTOR`.
- Expenses use single payee field: `EXPNAME`.
- Debt uses creditor/name field: `DBTNAME`.
- Receipts use source/name field: `RECNAME`.
- Filing index uses filer/committee name in `FILERNAME`.

## Employer/occupation
- Contributions include occupation in `OCCUPATION` and employer/entity context in `ENAME` plus employer address fields (`EADDRESS1`, `EADDRESS2`, `ECITY`, `ESTATE`, `EZIPCODE`).
- Expense, debt, receipt, and filer index files do not provide person-level occupation columns.

## Address format
- Contribution/expense/debt/receipt rows use `ADDRESS1`, `ADDRESS2`, `CITY`, `STATE`, `ZIPCODE`.
- Contribution rows additionally include employer address columns prefixed with `E*`.
- ZIP values include 5-digit and ZIP+4 strings (for example `17403-2013`).
- Empty strings are common for optional address lines.

## Committee IDs
Native identifiers observed:
- Filing identifier: `CampaignFinanceID` (or `CampaignfinanceID` in `filer_2025.txt` header capitalization).
- Committee/filer identifier: `FILERID` / `FilerID` (mixed numeric and alphanumeric values observed, e.g., `2004206`, `2025C0033`).

Mapping decisions:
- `source_record_key`
  - Filing rows (`filer_2025.txt`): `CampaignfinanceID`
  - Transaction/detail rows (`contrib`, `expense`, `debt`, `receipt`): deterministic hash fallback of full raw row (no native row-unique transaction ID column observed).
- `transaction_identifier`
  - Transaction/detail rows: same deterministic hash fallback as `source_record_key`.
- `filing_fec_id`
  - `PA-{FILERID}-{SubmittedDate[0:4]}-{data_type}`

## Amendment handling
Observed amendment-like fields:
- `filer_2025.txt` has `AMMEND` and `TERMINATE` with values `Y`/`N`.
- Detail transaction files (`contrib`, `expense`, `debt`, `receipt`) do not include amendment flags.

Mapping decision for `AmendmentIndicatorLiteral` (filing-level):
- `A`: `AMMEND == "Y"`
- `T`: `AMMEND != "Y"` and `TERMINATE == "Y"`
- `N`: otherwise

Detail-row handling note:
- Transaction files lack amendment columns.
- All four 2025 detail-file headers include `CampaignFinanceID`, which corresponds to the filing identifier column in `filer_2025.txt` aside from the filer index's capitalization variant `CampaignfinanceID`.
- Stage 1 deferral: implementation must derive each detail row's `amendment_indicator` by joining detail-row `CampaignFinanceID` to filing-row `CampaignfinanceID`.
- If a detail row cannot be joined to a filing row, the amendment state is unresolved from source data and should stay an explicit deferred linkage issue rather than defaulting to `N`.

## Missing/null conventions
- Empty strings represent null/missing text in most columns.
- Contributions use `0` / `0.00` in secondary/tertiary contribution date/amount fields when absent.
- Some transaction-date fields are blank (`EXPDATE`, `DBTDATE`, `RECDATE` observed blanks in inventory parsing).

## Portal Navigation
PA DOS yearly exports are direct downloads from static links.
1. Entry page: `https://www.pa.gov/agencies/dos/resources/voting-and-elections-resources/campaign-finance-data`
2. URL pattern observed for most years: `.../campaign-finance-data/{YEAR}.zip` (for example `2026.zip`, `2024.zip`, `2023.zip`).
3. 2025 is a naming exception: `2025%20campaign%20finance%20full%20export%20.zip`.
4. Download yearly ZIP, then inspect member text files.

## Exact header rows (all CSV types in 2025 archive)
Contributions (`contrib_2025.txt`):
```text
CampaignFinanceID,FilerID,EYEAR,SubmittedDate,CYCLE,Section,CONTRIBUTOR,ADDRESS1,ADDRESS2,CITY,STATE,ZIPCODE,OCCUPATION,ENAME,EADDRESS1,EADDRESS2,ECITY,ESTATE,EZIPCODE,CONTDATE1,CONTAMT1,CONTDATE2,CONTAMT2,CONTDATE3,CONTAMT3,CONTDESC
```

Expenses (`expense_2025.txt`):
```text
CampaignFinanceID,FILERID,EYEAR,SubmittedDate,CYCLE,EXPNAME,ADDRESS1,ADDRESS2,CITY,STATE,ZIPCODE,EXPDATE,EXPAMT,EXPDESC
```

Debt (`debt_2025.txt`):
```text
CampaignFinanceID,FILERID,EYEAR,SubmittedDate,CYCLE,DBTNAME,ADDRESS1,ADDRESS2,CITY,STATE,ZIPCODE,DBTDATE,DBTAMT,DBTDESC
```

Filer index (`filer_2025.txt`):
```text
CampaignfinanceID,FILERID,EYEAR,SubmittedDate,CYCLE,AMMEND,TERMINATE,FILERTYPE,FILERNAME,OFFICE,DISTRICT,PARTY,ADDRESS1,ADDRESS2,CITY,STATE,ZIPCODE,COUNTY,PHONE,BEGINNING,MONETARY,INKIND
```

Receipts (`receipt_2025.txt`):
```text
CampaignFinanceID,FILERID,EYEAR,SubmittedDate,CYCLE,RECNAME,ADDRESS1,ADDRESS2,CITY,STATE,ZIPCODE,RECDESC,RECDATE,RECAMT
```

## Open questions
- Portal discrepancy observed on 2026-03-21: the link labeled "2002 Full Export" points to `/campaign-finance-data/2022.zip` on the page HTML. This should be re-verified before automation.

## Stage 10 freshness source decision (2026-03-23)
Decision:
- No qualifying fresher official machine-readable PA source is implementation-ready as of 2026-03-23.
- The Department of State online campaign-finance database is official and appears more frequent than annual ZIP exports, but machine export/API contract and full office-level scope parity are not yet verified under anti-bot/session constraints.
- Annual ZIP archives remain the canonical ingest source for this jurisdiction package.

Operator evidence captured:
- Official annual source-of-record export page is PA Department of State campaign-finance data: `https://www.pa.gov/agencies/dos/resources/voting-and-elections-resources/campaign-finance-data` (yearly full-export ZIP links, including `2026.zip` and a 2025 naming exception).
- Official PA Department of State service page confirms online report search and states filings occur throughout the cycle: `https://www.pa.gov/services/dos/search-political-campaign-finance-reports`.
- Official PA online campaign-finance database endpoint linked by DOS: `https://www.campaignfinanceonline.pa.gov/pages/CFReportSearch.aspx`. Stage 10 operator probing observed Incapsula perimeter/session behavior (`visid_incap_*`, `incap_ses_*`) that prevented browserless verification of stable machine-export/API parameters.
- Socrata catalog probes for `data.pa.gov` returned no campaign-finance datasets/API candidates:
  - `https://api.us.socrata.com/api/catalog/v1?domains=data.pa.gov&search_context=data.pa.gov&q=campaign%20finance&limit=10`
  - `https://api.us.socrata.com/api/catalog/v1?domains=data.pa.gov&search_context=data.pa.gov&q=campaign&limit=10`
  - `https://api.us.socrata.com/api/catalog/v1?domains=data.pa.gov&search_context=data.pa.gov&q=political%20committee&limit=10`

Carry-forward limitation text for later config/README update:
- `PA online database exists but machine export/API + scope parity are unverified; annual full-export ZIP remains canonical.`

Open questions:
- Confirm whether the PA online database exposes stable, automatable export/API endpoints without anti-bot breakage.
- Confirm full office-level scope parity (state + county + municipal) between the online database export surface and the annual ZIP contract.
