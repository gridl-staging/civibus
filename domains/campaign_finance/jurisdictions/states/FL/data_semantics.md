# Florida DOS campaign-finance data semantics

Observed from live exports and Stage 1 fixtures on 2026-03-25.

## File format contract
- Delimiter: tab (`\t`)
- Line endings: CRLF (`\r\n`)
- Encoding: US-ASCII
- Header row: present on first line
- Quoting: none as a CSV enclosure rule; double quotes are literal data content

## Field formats by transaction type

### Shared core fields
- `Candidate/Committee`: combined committee/candidate display name
- `Date`: `MM/DD/YYYY`
- `Amount`: decimal string with two fractional digits (for example `5000.00`, `-100000.00`)
- `Address`: single street-line value
- `City State Zip`: combined locality string (for example `MIAMI, FL 33143`)

### Contributions
- `Typ`: contribution classification code (for example `CHE` in fixture sample)
- `Contributor Name`: single combined name field, not split first/last
- `Occupation`: free-text occupation
- `Inkind Desc`: optional in-kind description; empty trailing field is common

### Expenditures
- `Payee Name`: single payee display name
- `Purpose`: free-text purpose/description
- `Type`: expenditure type code (for example `MON` in fixture sample)

### Transfers
- `Funds Transferred To`: receiving account/payee name
- `Nature Of Account`: account category text (for example `MM` in fixture sample)
- `Type`: transfer type code (for example `F` in fixture sample)

### Other disbursements
- `Distributed To`: receiving payee name
- `Purpose`: free-text disbursement purpose

## Null and optional value behavior
- Empty cells are represented as empty trailing tab fields.
- Parsers normalize empty strings to `None`.
- No alternate null sentinels (such as `NA` or `N/A`) are currently documented for FL fixtures.
