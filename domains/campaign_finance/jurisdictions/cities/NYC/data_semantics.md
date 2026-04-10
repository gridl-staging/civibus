# New York City campaign-finance data semantics

Machine-readable mapping authority is `config.yaml`.
This file records assumptions for the NYC city-config scaffold.

## Acquisition contract summary
- Primary endpoint: `https://www.nyccfb.info/datalibrary/{YEAR}_Contributions.csv`
- Bulk archive: `https://www.nyccfb.info/DataLibrary/CFB-Data.zip`
- Platform: Static CSV/ZIP download (T1 — no API, no authentication)
- Auth: none

## Field inventory scope
The current config maps the 52-column contribution inventory from the
NYC CFB Data Library and defines each mapped column below.

## Transaction column definitions
| Source column | Canonical mapping | Definition |
| --- | --- | --- |
| `ELECTION` | `nyc.election_cycle` | Election cycle year (e.g. 2025, 2021). |
| `OFFICECD` | `nyc.office_code` | Office sought code (1=Mayor, 2=Public Advocate, etc.). |
| `RECIPID` | `committee.cfb_id` | Recipient/filer ID assigned by NYC CFB. |
| `CANCLASS` | `nyc.candidate_classification` | Campaign Finance Program classification. |
| `RECIPNAME` | `committee.name` | Recipient/filer name. |
| `COMMITTEE` | `committee.committee_id` | Committee ID assigned by CFB. |
| `FILING` | `filing.period` | Disclosure statement filing period number. |
| `SCHEDULE` | `nyc.schedule` | Schedule type (ABC, D, G, K, M, N, ICONT, etc.). |
| `PAGENO` | `nyc.page_number` | Page number of schedule. |
| `SEQUENCENO` | `nyc.sequence_number` | Sequence number on page. |
| `REFNO` | `transaction.id` | Transaction reference number. |
| `DATE` | `transaction.date` | Date contribution received (M/D/YYYY format). |
| `REFUNDDATE` | `nyc.refund_date` | Date of refund or loan forgiven (M/D/YYYY format). |
| `NAME` | `donor.name` | Contributor name (single field). |
| `C_CODE` | `donor.type_code` | Contributor type code (IND, CORP, LLC, PCOMP, etc.). |
| `STRNO` | `donor.address.street_number` | Contributor street number. |
| `STRNAME` | `donor.address.street_name` | Contributor street name. |
| `APARTMENT` | `donor.address.apartment` | Contributor apartment number. |
| `BOROUGHCD` | `nyc.borough_code` | Contributor NYC borough code. |
| `CITY` | `donor.address.city` | Contributor city. |
| `STATE` | `donor.address.state` | Contributor state. |
| `ZIP` | `donor.address.zip` | Contributor ZIP code. |
| `OCCUPATION` | `donor.occupation` | Contributor occupation. |
| `EMPNAME` | `donor.employer` | Contributor employer name. |
| `EMPSTRNO` | `donor.employer_address.street_number` | Employer street number. |
| `EMPSTRNAME` | `donor.employer_address.street_name` | Employer street name. |
| `EMPCITY` | `donor.employer_address.city` | Employer city. |
| `EMPSTATE` | `donor.employer_address.state` | Employer state. |
| `AMNT` | `transaction.amount` | Contribution amount (numeric). |
| `MATCHAMNT` | `nyc.matchable_amount` | Matchable amount of contribution. |
| `PREVAMNT` | `nyc.previous_contributions_total` | Total of previous contributions from this donor. |
| `PAY_METHOD` | `nyc.payment_method` | Payment method code. |
| `INTERMNO` | `intermediary.number` | Intermediary number. |
| `INTERMNAME` | `intermediary.name` | Intermediary name. |
| `INTSTRNO` | `intermediary.address.street_number` | Intermediary street number. |
| `INTSTRNM` | `intermediary.address.street_name` | Intermediary street name. |
| `INTAPTNO` | `intermediary.address.apartment` | Intermediary apartment number. |
| `INTCITY` | `intermediary.address.city` | Intermediary city. |
| `INTST` | `intermediary.address.state` | Intermediary state. |
| `INTZIP` | `intermediary.address.zip` | Intermediary ZIP code. |
| `INTEMPNAME` | `intermediary.employer` | Intermediary employer name. |
| `INTEMPSTNO` | `intermediary.employer_address.street_number` | Intermediary employer street number. |
| `INTEMPSTNM` | `intermediary.employer_address.street_name` | Intermediary employer street name. |
| `INTEMPCITY` | `intermediary.employer_address.city` | Intermediary employer city. |
| `INTEMPST` | `intermediary.employer_address.state` | Intermediary employer state. |
| `INTOCCUPA` | `intermediary.occupation` | Intermediary occupation. |
| `PURPOSECD` | `nyc.purpose_code` | Purpose code for in-kind contributions. |
| `EXEMPTCD` | `nyc.exempt_code` | Exempt code. |
| `ADJTYPECD` | `nyc.adjustment_type_code` | Schedule M adjustment type code. |
| `RR_IND` | `nyc.runoff_rerun_indicator` | Runoff/rerun indicator. |
| `SEG_IND` | `nyc.segregated_indicator` | Segregated indicator. |
| `INT_C_CODE` | `intermediary.type_code` | Intermediary name/type code. |

## Date fields
- `DATE` and `REFUNDDATE` use M/D/YYYY format (e.g. "1/3/2025", "12/15/2024").
- This differs from SF/LA which use ISO 8601 timestamps.

## Name formats
- Contributor names are a single field (`NAME`), not split into first/last.
- Recipient names use "Last, First" format in `RECIPNAME`.

## Employer/occupation
- Donor occupation and employer come from `OCCUPATION` and `EMPNAME`.
- Employer address fields are present (`EMPSTRNO`, `EMPSTRNAME`, `EMPCITY`, `EMPSTATE`).
- Intermediary occupation/employer are modeled separately via `INT*` fields.

## Address format
- Donor and intermediary addresses include street number, street name, apartment, city, state, zip.
- Borough code (`BOROUGHCD`) is an NYC-specific field with values: M(Manhattan), Q(Queens), K(Brooklyn), X(Bronx), R(Staten Island).

## Amendment handling
- Filing/version supersession semantics are not implemented in this initial pass.
- Raw contribution records are preserved for provenance-first ingestion.

## Missing/null conventions
- Empty source values should normalize to null.
- Free-text fields are preserved as-is for provenance-first ingestion.
