# Georgia Campaign Portal Data Semantics

Field-by-field parsing and normalization rules based on live portal exports captured on 2026-03-21.

## Date fields

- Contribution and expenditure exports both emit date-like values with a midnight timestamp suffix: `M/D/YYYY 12:00:00 AM`.
- Normalize to `YYYY-MM-DD` for transaction dates.
- Election year is a separate numeric field (`Election_Year`) and should not be inferred from `Date`.
- Source timezone is not explicitly declared; treat as Georgia local filing context (`America/New_York`) when deriving temporal windows.

## Name formats

- Contributions split donor name into `LastName` and `FirstName`; entity donors often appear entirely in `LastName` with empty `FirstName`.
- Candidate name is split into `Candidate_FirstName`, `Candidate_MiddleName`, `Candidate_LastName`, `Candidate_Suffix`.
- Expenditure exports use `LastName`/`FirstName` for payee identity with similar entity-in-last-name behavior.
- Preserve source casing for raw storage; apply title-casing only in normalized presentation layers.

## Employer/occupation

- Contribution exports provide separate `Occupation` and `Employer` columns.
- Expenditure exports collapse this into a single `Occupation_or_Employer` field.
- Blank values are common and should map to explicit `null` in normalized records.

## Address format

- Address is a single street line (`Address`) plus city/state/zip components.
- Contribution exports contain mixed-casing state values (for example `ga`); normalize to uppercase postal abbreviation.
- No dedicated `Address2` field is present in either export format.

## Committee IDs

- `FilerID` is the stable committee identifier used across search surfaces.
- Observed format is `C` + digits (for example `C2006000122`), but treat as opaque string rather than typed integer.
- `Committee_Name` is the committee display name linked to `FilerID`.

## Amendment handling

- Contribution and expenditure exports do **not** include explicit amendment/supersession flags.
- Amendment context appears in report-log records (`Original` vs `Amended`) rather than in the export transaction rows.
- Normalization should keep append semantics for raw exports and resolve amendment precedence only after joining with report-log or filing-detail data.
- The loader unconditionally sets `amendment_indicator='N'` on all filing and transaction rows because the portal export does not carry amendment flags.

## Missing/null conventions

- Contribution CSV export uses empty quoted fields (`""`) for missing values.
- Expenditure export uses HTML entities such as `&nbsp;` in table cells for missing values.
- Numeric amount fields are decimal strings with four fractional digits (`25.0000`, `0.0000`).

## Export file encoding and metadata rows

- Contribution CSV export (`StateEthicsReport.csv`) is ASCII-compatible text with CRLF line terminators; no BOM or explicit charset header is sent. Parse as UTF-8 (ASCII superset).
- Expenditure export (`EthicsReportExport.xls`) is ASCII-compatible HTML with CRLF line terminators; no encoding declaration beyond standard ASCII. Parse as UTF-8.
- Neither export file contains portal-added metadata rows (no title row, no trailing summary row, no report-generation timestamp row). The first row is the header and all subsequent rows are data records.

## Available portal search surfaces

The campaign search portal at `media.ethics.ga.gov/search/Campaign/` exposes five public search surfaces:

| Surface | Page | Export available | Used in this stage |
|---|---|---|---|
| Search by Contribution | `Campaign_ByContributions.aspx` | Yes (CSV) | Yes |
| Search by Expenditure | `Campaign_ByExpenditures.aspx` | Yes (HTML-table .xls) | Yes |
| View Campaign Report Log | `Campaign_ReportLog.aspx` | No export observed | No |
| Search by Name | `Campaign_ByName.aspx` | No export observed | No |
| Search by Office | `Campaign_ByOffice.aspx` | No export observed | No |

Only the contribution and expenditure surfaces provide data-export functionality. The report-log, name-search, and office-search surfaces are navigational/lookup views without bulk-export triggers observed during verification.

## Portal Navigation

Use a single Playwright browser context; this portal is stateful and postback-driven.

1. Navigate to `https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx`.
2. Fill at least one search criterion (for deterministic sampling, use candidate + date range).
3. Submit via `#ctl00_ContentPlaceHolder1_Search`.
4. On results page (`...Campaign_ByContributionsearchresults.aspx?...`):
   - Pagination is ASP.NET postback (`__doPostBack`) and page-size table renders 10 rows per page.
   - `#ctl00_ContentPlaceHolder1_lblPageInfo` reports current page/total pages.
5. Trigger export via `#ctl00_ContentPlaceHolder1_Export`.
   - For Playwright, use `click(no_wait_after=True)` with `expect_download(...)` to avoid navigation deadlock.
   - Contribution export response is `text/csv` attachment `StateEthicsReport.csv`.
   - The payload is a CSV payload with .xls extension in local save paths when callers force `.xls` names.
6. Export semantics: export returns full result set across all pages, not the currently visible page.
7. Keep the same browser context for search -> pagination -> export; reusing stale hidden state in raw HTTP scripts often times out.

Expenditure flow is parallel via `Campaign_ByExpenditures.aspx`:

- Export attachment is `EthicsReportExport.xls` with MIME `application/vnd.ms-excel`.
- Payload is an HTML table payload with .xls attachment metadata, not an OOXML workbook.
- Use the same single browser context/session discipline for ASP.NET postbacks.
