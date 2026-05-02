# North Carolina campaign-finance law notes

This file supports the structured `laws` block in `config.yaml`.

## Authoritative source
- Contribution limits and election-period definition: https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.13.html
- Itemization threshold and required contribution/expenditure disclosure fields: https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.11.html
- Candidate/political-committee reporting cadence and electronic-filing trigger classes: https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.9.html
- Prohibited corporate/business/labor/professional/insurance contributions: https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.15.html and https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.19.html
- Municipal report schedules (Part 2):
  - https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.40B.html
  - https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.40C.html
  - https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.40D.html
  - https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.40E.html
- NCSBE operational electronic-filing guidance (including 08 NCAC 21 .0106 reference): https://www.ncsbe.gov/campaign-finance/campaign-finance-reporting-software
- Public Campaign Fund repeal marker in current Chapter 163 index: https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter163

## Contribution limits table
- `individual_to_candidate`: $6,800 per election (`G.S. 163-278.13(a)`)
- `pac_to_candidate`: $6,800 per election (`G.S. 163-278.13(a)` and definition of political committee)
- `corporate_direct`: prohibited (`G.S. 163-278.15(a)` and `G.S. 163-278.19(a)`)
- `union_direct`: prohibited (`G.S. 163-278.15(a)` and `G.S. 163-278.19(a)`)
- `party_to_candidate`: unlimited in this flat schema because `G.S. 163-278.13(h)` exempts national/state/district/county party executive committees and affiliated party committees from `163-278.13` limits

Additional statutory nuance:
- Candidate and candidate-spouse self-funding is unlimited (`G.S. 163-278.13(d)`).
- Reimbursed contribution carve-out exists for qualifying reimbursements up to $1,000 (`G.S. 163-278.13(f)`/`(g)`).

## Itemization threshold
- Contributor identity fields (name, address, principal occupation) are not required for individuals contributing $50 or less in an election (`G.S. 163-278.11(b)`).
- For contributions above that threshold, reports must include contributor identity plus occupation/employer field data (`G.S. 163-278.11(a)(1)`).

## Sub-state committee registration exemption
- `G.S. 163-278.10A` exempts certain sub-state candidates from full campaign-committee registration when total contributions, expenditures, AND loans each remain at or below $1,000 across the election.
- Applies to: county, municipal, school-board, and special-district candidates only.
- Does NOT apply to federal or state-level candidates (Governor, Council of State, NCGA, judicial), who must register a committee regardless of fundraising volume.
- Statute reference: https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-278.10A.html
- Operational consequence: below-threshold sub-state candidates legitimately have NO NC CF data anywhere. UI must distinguish "expected absence (under threshold)" from "above threshold but missing (possible non-compliance)" from "transactions not yet ingested by us."

## Reporting periods and deadlines
- `G.S. 163-278.9(a)` drives state-level candidate/political-committee schedules:
  - Organizational report due within 10 days.
  - Quarterly windows in election years.
  - Semiannual reporting when no other report is required.
  - 48-hour report for qualifying $1,000+ receipts/transfers after the last pre-election reporting period.
- Municipal offices are governed by Part 2 (`G.S. 163-278.40B`–`40E`) and include thirty-five-day and 10-day pre-election style reports plus semiannual reporting.
- Electronic filing is required when filer classes exceed thresholds in `G.S. 163-278.9(i)`; NCSBE software guidance operationalizes these requirements and references 08 NCAC 21 .0106.

## Prohibitions
- Anonymous or straw-donor contributions are prohibited (`G.S. 163-278.14`).
- Cash-like monetary contributions above $50 must be in traceable noncash forms (`G.S. 163-278.14(b)`).
- Direct corporate/business/labor/professional/insurance contributions are prohibited, with segregated-fund and other statutory exceptions in `G.S. 163-278.19`.

## Public financing
- No active statewide public-financing program is reflected in current Chapter 163 codification.
- Current Chapter 163 index marks `G.S. 163-278.61` through `163-278.67` (Article 22D, North Carolina Public Campaign Fund) as repealed effective July 1, 2013.

## Known ambiguities / recent changes
- Portal document-type options still include legacy labels such as `Report - Judicial Qualifying Contributions` and `Report - Municipal Voter-Owned Election Qualifying Contributions`; these appear to represent historical report categories and do not, by themselves, prove an active public-financing program.
- Contribution-limit amounts are CPI-adjusted in odd-numbered years under `G.S. 163-278.13(b)`, so future cycles require re-verification.

## Office-level or election-type variation
- Municipal election report schedules vary by election method (`G.S. 163-278.40B` through `G.S. 163-278.40E`).
- State-level schedules in `G.S. 163-278.9` differ from municipal schedules and referendum schedules (`G.S. 163-278.9A`), so normalizers should keep office/election-context metadata when reconciling report deadlines across jurisdictions.
