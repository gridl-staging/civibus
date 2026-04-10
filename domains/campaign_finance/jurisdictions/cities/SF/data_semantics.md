# San Francisco campaign-finance data semantics

Machine-readable mapping authority is `config.yaml`.
This file records assumptions for the Stage 2 SF city-config scaffold.

## Acquisition contract summary
- Primary endpoint: `https://data.sfgov.org/resource/pitq-e56w.{json|csv}`
- API metadata endpoint: `https://data.sfgov.org/api/views/pitq-e56w.json`
- Platform: Socrata (SODA API), same platform family as WA state pipeline
- Auth: none

## Field inventory scope
The current config maps the 56-column Stage 1 transaction inventory from
`pitq-e56w` and defines each mapped column below.

## Transaction column definitions
| Source column | Canonical mapping | Definition |
| --- | --- | --- |
| `filing_id_number` | `filing.id` | NetFile/SF filing identifier for the submitted report. |
| `filing_date` | `filing.date` | Filing submission date recorded by the SF Ethics dataset. |
| `start_date` | `filing.period_start` | Filing period start date for the reported activity window. |
| `end_date` | `filing.period_end` | Filing period end date for the reported activity window. |
| `fppc_id` | `sf.fppc_id` | FPPC filer identifier surfaced in the SF dataset. |
| `filer_name` | `committee.name` | Committee or filer name attached to the filing. |
| `filer_type` | `committee.type` | Filer category as published by SF Ethics. |
| `calculated_amount` | `sf.calculated_amount` | Derived amount field provided by the source system. |
| `calculated_date` | `sf.calculated_date` | Derived date field provided by the source system. |
| `form_type` | `sf.form_type` | FPPC form type for the transaction row (for example, 460/496/497). |
| `transaction_id` | `transaction.id` | Source transaction identifier within the filing context. |
| `transaction_first_name` | `donor.first_name` | Contributor first name for person contributors. |
| `transaction_last_name` | `donor.last_name` | Contributor last name for person contributors. |
| `transaction_amount_1` | `transaction.amount` | Primary transaction amount used for canonical ingest. |
| `transaction_amount_2` | `sf.transaction_amount_secondary` | Secondary amount field retained for SF-specific provenance. |
| `transaction_date` | `transaction.date` | Primary transaction date used for canonical ingest. |
| `transaction_date_1` | `sf.transaction_date_secondary` | Secondary transaction date retained for SF-specific provenance. |
| `transaction_description` | `transaction.description` | Free-text description for the transaction entry. |
| `transaction_city` | `donor.address.city` | Contributor city value from the transaction record. |
| `transaction_state` | `donor.address.state` | Contributor state value from the transaction record. |
| `transaction_zip` | `donor.address.zip` | Contributor ZIP or postal code from the transaction record. |
| `transaction_name_title` | `donor.name_title` | Contributor honorific/title if provided. |
| `transaction_name_suffix` | `donor.name_suffix` | Contributor suffix if provided (for example, Jr/Sr). |
| `transaction_occupation` | `donor.occupation` | Contributor occupation text. |
| `transaction_employer` | `donor.employer` | Contributor employer text. |
| `transaction_self` | `sf.transaction_self_reported` | Source flag indicating self-reporting/self-contribution context. |
| `transaction_check_number` | `sf.check_number` | Check number or payment reference text from the source. |
| `transaction_code` | `transaction.type` | Source transaction-type code used to classify the transaction. |
| `treasurer_first_name` | `committee.treasurer.first_name` | Treasurer first name for the filing committee. |
| `treasurer_last_name` | `committee.treasurer.last_name` | Treasurer last name for the filing committee. |
| `treasurer_name_title` | `committee.treasurer.name_title` | Treasurer honorific/title value if present. |
| `treasurer_name_suffix` | `committee.treasurer.name_suffix` | Treasurer suffix value if present. |
| `treasurer_city` | `committee.treasurer.address.city` | Treasurer city from filing contact details. |
| `treasurer_state` | `committee.treasurer.address.state` | Treasurer state from filing contact details. |
| `treasurer_zip` | `committee.treasurer.address.zip` | Treasurer ZIP or postal code from filing contact details. |
| `intermediary_committee_id` | `sf.intermediary_committee_id` | Committee identifier for an intermediary entity when reported. |
| `intermediary_first_name` | `intermediary.first_name` | Intermediary first name for bundled/intermediated activity. |
| `intermediary_last_name` | `intermediary.last_name` | Intermediary last name for bundled/intermediated activity. |
| `intermediary_name_title` | `intermediary.name_title` | Intermediary honorific/title if provided. |
| `intermediary_name_suffix` | `intermediary.name_suffix` | Intermediary suffix if provided. |
| `intermediary_employer` | `intermediary.employer` | Intermediary employer text. |
| `intermediary_occupation` | `intermediary.occupation` | Intermediary occupation text. |
| `intermediary_selfemployed` | `sf.intermediary_self_employed` | Source self-employed indicator for intermediary records. |
| `intermediary_city` | `intermediary.address.city` | Intermediary city value. |
| `intermediary_state` | `intermediary.address.state` | Intermediary state value. |
| `intermediary_zip` | `intermediary.address.zip` | Intermediary ZIP or postal code value. |
| `lender_name` | `lender.name` | Lender name for loan-related entries. |
| `interest_rate` | `loan.interest_rate` | Interest rate value attached to loan records. |
| `loan_amount_1` | `loan.amount_1` | Loan amount slot 1 as published in the source extract. |
| `loan_amount_2` | `loan.amount_2` | Loan amount slot 2 as published in the source extract. |
| `loan_amount_3` | `loan.amount_3` | Loan amount slot 3 as published in the source extract. |
| `loan_amount_4` | `loan.amount_4` | Loan amount slot 4 as published in the source extract. |
| `loan_amount_5` | `loan.amount_5` | Loan amount slot 5 as published in the source extract. |
| `loan_amount_6` | `loan.amount_6` | Loan amount slot 6 as published in the source extract. |
| `loan_amount_7` | `loan.amount_7` | Loan amount slot 7 as published in the source extract. |
| `loan_amount_8` | `loan.amount_8` | Loan amount slot 8 as published in the source extract. |

## Date fields
- `filing_date`, `start_date`, `end_date`, `transaction_date`, and `transaction_date_1`
  are treated as date-like fields and normalized downstream to canonical date values.

## Name formats
- Contributor names are split (`transaction_first_name`, `transaction_last_name`) with
  optional title/suffix fields.
- Committee and treasurer names are represented in separate field families.

## Employer/occupation
- Donor occupation and employer come from `transaction_occupation` and
  `transaction_employer`.
- Intermediary occupation/employer are modeled separately via `intermediary_*` fields.

## Address format
- Donor, treasurer, and intermediary addresses are currently modeled as city/state/zip.
- Street-line details are not present in this baseline field set.

## Amendment handling
- Filing/version supersession semantics are not implemented in Stage 2.
- Raw filing identifiers are preserved for later deduplication/upsert behavior.

## Missing/null conventions
- Empty source values should normalize to null.
- Free-text fields are preserved as-is for provenance-first ingestion.
