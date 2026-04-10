# Ohio campaign-finance law notes

This file is narrative support for the OH `laws` block in `config.yaml`.

## Authoritative sources
- Ohio Revised Code Title XXXV, Chapter 3517 (campaign finance regulation): <https://codes.ohio.gov/ohio-revised-code/chapter-3517>
- ORC §3517.102 (dollar limits on campaign contributions): <https://codes.ohio.gov/ohio-revised-code/section-3517.102>
- ORC §3517.104 (CPI adjustment of contribution limits): <https://codes.ohio.gov/ohio-revised-code/section-3517.104>
- ORC §3517.106 (electronic filing requirements): <https://codes.ohio.gov/ohio-revised-code/section-3517.106>
- ORC §3517.10 (campaign committees and reporting): <https://codes.ohio.gov/ohio-revised-code/section-3517.10>
- ORC §3599.03 (prohibited use of corporate and labor organization funds): <https://codes.ohio.gov/ohio-revised-code/section-3599.03>
- Ohio SOS campaign finance landing page: <https://www.ohiosos.gov/campaign-finance/>
- Ohio SOS campaign finance laws and rules: <https://www.ohiosos.gov/campaign-finance/laws-and-rules/>
- Ohio SOS contribution limits chart (2025): <https://www.ohiosos.gov/globalassets/candidates/limitchart2025.pdf>
- Ohio SOS adjusted campaign contribution limits booklet (2025): <https://www.ohiosos.gov/globalassets/candidates/limitsbooklet2025.pdf>

## CPI adjustment mechanism
ORC §3517.104 requires the Secretary of State to adjust all contribution limits in §3517.102 for inflation every odd-numbered year using the CPI for All Urban Consumers (base year 1996). The current adjustment period is **2025-02-25 through 2027-02-24**. All dollar amounts below reflect the current CPI-adjusted values, not the base statutory amounts.

## Contribution limits table (CPI-adjusted, effective 2025-02-25)
- Individual to candidate: **$16,615.67** per election period (primary or general). Base: $10,000 per ORC §3517.102, adjusted per §3517.104. `config.yaml` uses $16,616 (rounded).
- PAC/PCE to candidate: **$16,615.67** per election period (primary or general). Same base and adjustment.
- Corporate direct to candidate: **prohibited** per ORC §3599.03. Corporations may form PACs and may contribute up to $10,000 per calendar year to a state political party restricted fund per ORC §3517.102(X)(3)(a).
- Union direct to candidate: **prohibited** per ORC §3599.03. Labor organizations may form PACs and may contribute up to $10,000 per calendar year to a state political party restricted fund per ORC §3517.102(X)(3)(a).
- Party to candidate (via state candidate fund): varies by office — **$937,123.77** statewide, **$186,926.28** senate, **$93,047.75** house per election period (all CPI-adjusted). `config.yaml` uses $93,048 (lowest tier, rounded).

## Itemization threshold
- ORC §3517.10(B)(4)(e) requires committees to keep a separate account of each contribution and expenditure regardless of amount, subject to a narrow exception for contributions of **$50 or less** from a person at one social or fund-raising activity and payroll-deduction contributions of **$50 or less** in a calendar year.
- The Ohio SOS 2025 adjusted-limits booklet shows the parallel adjusted threshold for separately identifying in-kind contributions received at a social or fund-raising activity as **more than $425** from one contributor.
- Contributions exceeding $100 still require disclosure of the donor's employer and occupation.
- `config.yaml` uses `itemization_threshold: 50` because this field tracks the lowest current threshold below which Ohio still permits aggregated reporting, not the separate employer/occupation disclosure trigger.

## Reporting periods and deadlines
- Semiannual report: due by 4:00 PM on the last business day of July.
- Annual report: due by 4:00 PM on the last business day of January.
- Pre-election report: due by 4:00 PM on the 12th day before an election, required if the committee spent or received $1,000 or more.
- Post-general election statement: required after general elections per ORC §3517.10.

## Electronic filing
- ORC §3517.106 mandates electronic filing for campaign committees of statewide candidates, General Assembly candidates, appeals court judges, PACs, and state/county parties when contributions or expenditures exceed $10,000 in a reporting period.
- Local candidates below the $10,000 threshold may file on paper but are permitted to file electronically.
- Hardship exemptions exist for committees with expenditures under $25,000, subject to procedural requirements.
- Filed information must be made publicly available within five business days.
- `config.yaml` sets `electronic_filing_required: "required"` because the mandatory threshold captures the majority of filers relevant to this platform's scope (statewide, legislative, judicial, PAC, and party committees).

## Public financing
- No Ohio public-financing scheme is modeled in this package (`public_financing: false`).

## Amendment handling
- No explicit amendment fields observed in bulk CSV exports (no `AMMEND`, `TERMINATE`, or `infoOnlyFlag` columns).
- `REPORT_DESCRIPTION` may contain amendment-related text (e.g., "Amended Annual Report") but this is unverified on live data.
- Interim approach: default all rows to `N` (new/original) absent a confirmed amendment field.
- Must be validated against live data when the APEX application returns from maintenance.

## Known ambiguities
- Cash contributions over $100 total per election are prohibited, but the electronic/in-kind threshold structure is less clear from statute text alone.
- Whether the APEX File Transfer Page includes post-2022 data is unverified due to ongoing maintenance.
- CPI-adjusted limits are recalculated every odd year; values in this file and `config.yaml` will need updating after 2027-02-24 when the next adjustment period begins.
- HB 96 (136th General Assembly, effective 2025-09-30) amended §3517.102; the base statutory amounts remain $10,000 but the bill's full impact on limit structure should be monitored.
