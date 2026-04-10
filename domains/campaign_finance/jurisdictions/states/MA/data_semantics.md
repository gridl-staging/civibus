# Massachusetts campaign-finance data semantics

This document captures parser and extraction assumptions for MA OCPF bulk data. Machine-readable mapping authority remains in `config.yaml`.

## Key fields

- **Item_ID**: Unique transaction line item identifier.
- **Report_ID**: Links to a specific filing report (join key to reports.txt).
- **Record_Type_ID**: Integer code differentiating transaction types:
  - 200-series (201-211): Receipts/contributions (individual, committee, union, corporate, in-kind, etc.)
  - 300-series (301-315): Expenditures (direct, bank fees, committee contributions, reimbursements, IE)
  - 400-series (401-405): In-kind contributions
  - 500-series (501-509): Liabilities
- **Related_CPF_ID**: OCPF Committee ID (CPF = Campaign/Political Finance). Used as the primary committee identifier.
- **Name**: Organization name or last name for individuals.
- **First_Name**: First name (populated only for individual donors/payees — key signal for person vs. org classification).
- **Date**: Transaction date (M/D/YYYY format).
- **Amount**: Transaction amount (decimal, may include $ prefix).

## File format

Tab-delimited .txt files inside ZIP archives. Windows line endings. Current year + 3 prior years regenerated nightly at ~07:30 UTC.
