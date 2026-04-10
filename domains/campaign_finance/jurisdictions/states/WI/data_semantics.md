# Wisconsin Sunshine export data semantics

Observed from live Wisconsin Sunshine CSV responses on 2026-03-26.

## Files and headers
- `transactions` export includes row-level transaction facts plus registrant context and optional related/final-recipient fields.
- `reports` export includes filing-period metadata and registrant metadata.
- `committees` export includes registrant-level status and filing metadata fields.

## CSV behavior
- Delimiter: comma.
- Quoting: standard CSV quoting with embedded newlines inside some quoted address fields.
- Field order: treated as contractually significant and validated by parser tests against config-derived columns.

## Semantics used in Stage 5 ingest
- Filing/committee identity anchor: `Registrant ID` + `Registrant Name`.
- Transaction date and amount anchor: `Date`, `Amount`.
- Transaction type anchor: `Transaction Type`.
- Counterparty anchor: contributor fields (`Contributor Name`, `Contributor Entity Type`, and contributor address components).

## Known caveats
- Export rows may contain multiline address values.
- No explicit per-transaction amendment indicator is exposed in the transaction export.
