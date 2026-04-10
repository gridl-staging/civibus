# Illinois Data Semantics

Evidence date: 2026-03-27.

## File Format

- `Receipts.txt` and `Expenditures.txt` are tab-delimited text files with a header row.
- The download responses were served as `application/octet-stream` attachments.
- The sample fixtures in `scraper/test_fixtures/` decode cleanly as UTF-8.

## Receipts

Observed header:

`ID, CommitteeID, FiledDocID, ETransID, LastOnlyName, FirstName, RcvDate, Amount, AggregateAmount, LoanAmount, Occupation, Employer, Address1, Address2, City, State, Zip, D2Part, Description, VendorLastOnlyName, VendorFirstName, VendorAddress1, VendorAddress2, VendorCity, VendorState, VendorZip, Archived, Country, RedactionRequested`

Key semantics confirmed from the live data dictionary:

- `ID`: per-row receipt identifier.
- `CommitteeID`: SBE committee identifier.
- `FiledDocID`: filing identifier for the report containing the receipt.
- `ETransID`: electronic-filing row identifier when present.
- `LastOnlyName` + `FirstName`: donor name fields. Business names commonly live entirely in `LastOnlyName`.
- `RcvDate`: receipt date/time string in `YYYY-MM-DD HH:MM:SS`.
- `Amount`: receipt amount in dollars.
- `AggregateAmount`: aggregate donor total for the filing period.
- `LoanAmount`: loan amount when the receipt is a loan.
- `D2Part`: receipt section code. The dictionary maps `1=individual contributions`, `2=transfers in`, `3=loans received`, `4=other receipts`, `5=in-kind contributions`.
- `Description`: free-text description, especially relevant for other receipts and in-kind entries.
- `Archived`: boolean-like `True`/`False` flag indicating the row was superseded by an amendment.

## Expenditures

Observed header:

`ID, CommitteeID, FiledDocID, ETransID, LastOnlyName, FirstName, ExpendedDate, Amount, AggregateAmount, Address1, Address2, City, State, Zip, D2Part, Purpose, CandidateName, Office, Supporting, Opposing, Archived, Country, RedactionRequested`

Key semantics confirmed from the live data dictionary:

- `ID`: per-row expenditure identifier.
- `CommitteeID`: SBE committee identifier.
- `FiledDocID`: filing identifier for the report containing the expenditure.
- `LastOnlyName` + `FirstName`: payee name fields. Business names commonly live entirely in `LastOnlyName`.
- `ExpendedDate`: expenditure date/time string in `YYYY-MM-DD HH:MM:SS`.
- `Amount`: expenditure amount in dollars.
- `AggregateAmount`: aggregate payee total for the filing period.
- `D2Part`: expenditure section code. The dictionary maps `6=transfers out`, `7=loans made`, `8=expenditures`, `9=independent expenditures`.
- `Purpose`: free-text purpose field.
- `CandidateName`, `Office`, `Supporting`, `Opposing`: populated for independent expenditures.
- `Archived`: boolean-like `True`/`False` flag indicating the row was superseded by an amendment.

## Data Quality Notes

- The official data dictionary says `Addresss2` in the prose section for receipts, but the live file header is `Address2`.
- ZIP values are padded with trailing spaces in live rows; the loader trims to ZIP5 digits when possible.
- Historical rows go back to the late 1990s in the live samples downloaded on 2026-03-27.
