# Los Angeles campaign-finance data semantics

Machine-readable mapping authority is `config.yaml`.
This file records assumptions for the LA city-config scaffold.

## Acquisition contract summary
- Primary endpoint: `https://data.lacity.org/resource/m6g2-gc6c.{json|csv}`
- API metadata endpoint: `https://data.lacity.org/api/views/m6g2-gc6c.json`
- Platform: Socrata (SODA API), same platform family as SF city and WA state pipelines
- Auth: none

## Field inventory scope
The current config maps the 30-column contribution inventory from
`m6g2-gc6c` and defines each mapped column below.

## Transaction column definitions
| Source column | Canonical mapping | Definition |
| --- | --- | --- |
| `con_date` | `transaction.date` | Date of the contribution transaction. |
| `con_name` | `donor.name` | Contributor name (single field, not split into first/last). |
| `con_city_nm` | `donor.address.city` | Contributor city value from the transaction record. |
| `con_state_nm` | `donor.address.state` | Contributor state value from the transaction record. |
| `con_zip_cd` | `donor.address.zip` | Contributor ZIP or postal code from the transaction record. |
| `con_occp` | `donor.occupation` | Contributor occupation text. |
| `con_empr` | `donor.employer` | Contributor employer text. |
| `cmt_nm` | `committee.name` | Committee or filer name attached to the filing. |
| `cmt_id` | `committee.fppc_id` | FPPC committee identifier; may be null for some filers. |
| `cmt_type` | `committee.type` | Committee category as published by LA Ethics. |
| `cand_name` | `candidate.name` | Candidate name associated with the committee (Last, First format). |
| `seat_desc` | `la.seat_description` | Description of the office being sought (e.g. Mayor, City Council Member). |
| `dist_num` | `la.district_number` | Council district number when applicable; null for citywide offices. |
| `con_type` | `transaction.type` | Source contribution-type classification. |
| `con_desc` | `transaction.description` | Free-text description for the contribution entry. |
| `con_amount` | `transaction.amount` | Primary contribution amount. May be negative for refunds. |
| `con_amount_pd_forgiven` | `la.amount_paid_or_forgiven` | Amount paid or forgiven for this transaction. |
| `form` | `la.form_type` | California campaign filing form type (e.g. CA460, CA497). |
| `schedule` | `la.schedule` | Form schedule designation (e.g. A, C). |
| `per_beg_date` | `filing.period_start` | Filing period start date for the reported activity window. |
| `per_end_date` | `filing.period_end` | Filing period end date for the reported activity window. |
| `election_date` | `la.election_date` | Date of the election associated with this filing period. |
| `election_desc` | `la.election_description` | Description of the election (e.g. "2026 City and LAUSD Elections"). |
| `int_name` | `intermediary.name` | Intermediary name for bundled/intermediated activity. |
| `int_city_nm` | `intermediary.address.city` | Intermediary city value. |
| `int_state_nm` | `intermediary.address.state` | Intermediary state value. |
| `int_zip_cd` | `intermediary.address.zip` | Intermediary ZIP or postal code value. |
| `int_occp` | `intermediary.occupation` | Intermediary occupation text. |
| `int_empr` | `intermediary.employer` | Intermediary employer text. |
| `memo` | `la.memo` | Free-text memo field for additional notes. |

## Date fields
- `con_date`, `per_beg_date`, `per_end_date`, and `election_date`
  are treated as date-like fields and normalized downstream to canonical date values.

## Name formats
- Contributor names are a single field (`con_name`), not split into first/last.
- Candidate names use "Last, First" format in `cand_name`.

## Employer/occupation
- Donor occupation and employer come from `con_occp` and `con_empr`.
- Intermediary occupation/employer are modeled separately via `int_*` fields.

## Address format
- Donor and intermediary addresses are modeled as city/state/zip.
- Street-line details are not present in this dataset.

## Amendment handling
- Filing/version supersession semantics are not implemented in this initial pass.
- Raw contribution records are preserved for provenance-first ingestion.

## Missing/null conventions
- Empty source values should normalize to null.
- Free-text fields are preserved as-is for provenance-first ingestion.
