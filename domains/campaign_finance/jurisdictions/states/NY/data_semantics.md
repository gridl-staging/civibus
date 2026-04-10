# New York campaign-finance data semantics

This document captures parser and extraction assumptions for NY SODA API datasets. Machine-readable mapping authority remains in `config.yaml`.

## Key fields

- **filer_id**: Numeric BOE-assigned filer ID (committee identifier). Used as `ny_filer_id` in entity resolution.
- **trans_number**: GUID transaction identifier. Used for deterministic pagination ordering.
- **sched_date**: Transaction date (floating_timestamp, ISO 8601 format from SODA).
- **org_amt**: Transaction amount (decimal).
- **filing_sched_abbrev**: Schedule type differentiating contribution types (A/B/C/D/G) from expenditures (F).
- **cntrbr_type_desc**: Contributor type (Individual, Corporation, Committee, etc.) — used for person vs. org classification.
- **flng_ent_name**: Entity organization name (for org donors/payees).
- **flng_ent_first_name / flng_ent_last_name**: Entity individual name components.
- **r_amend**: "Y" if the report was amended.

## Entity classification

Contributions use `cntrbr_type_desc` for person/org classification. Expenditures lack this field and fall back to heuristic classification based on field presence and organization keyword matching.
