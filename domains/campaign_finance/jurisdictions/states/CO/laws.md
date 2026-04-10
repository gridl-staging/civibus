# Colorado Campaign Finance Laws

Narrative support for the `laws` block in `config.yaml`. Research date: 2026-03-14.

## Authoritative sources

- **Colorado Constitution, Article XXVIII** (Amendment 27, adopted 2002): establishes contribution limits for statewide and legislative offices, prohibitions on corporate/union direct contributions, and disclosure requirements.
  - Source: https://leg.colorado.gov/colorado-constitution (Article XXVIII)
- **C.R.S. Title 1, Article 45** (Fair Campaign Practices Act): statutory campaign finance provisions including county/school/municipal limits, reporting requirements, and enforcement.
  - Source: https://olls.info/crs/crs2025-title-01.htm
- **8 CCR 1505-6** (Secretary of State Campaign and Political Finance Rules): administrative rules including CPI adjustment calculations.
  - Source: https://www.coloradosos.gov/pubs/rule_making/CurrentRules/8CCR1505-6CPF.pdf
- **SOS Contribution Limits page**: current adjusted amounts.
  - Source: https://www.coloradosos.gov/pubs/elections/CampaignFinance/limits/contributions.html

## Contribution limits table

Limits are per election cycle unless noted. Current amounts effective 2023-02-15 through 2027 per CPF Rule 10.17, adjusted by CPI (Denver-Boulder-Greeley) per Art. XXVIII § 3(13). Base amounts from 2002 constitutional text.

### Individual or Political Committee to Candidate

| Office | Limit/cycle |
|---|---|
| Governor / Lt. Governor | $725 |
| Attorney General | $725 |
| Secretary of State | $725 |
| State Treasurer | $725 |
| State Senate | $225 |
| State House | $225 |
| District Attorney | $225 |
| CU Regent | $225 |
| State Board of Education | $225 |
| County offices | $1,425 |
| School District Director | $2,500/election |
| Municipal offices | $400/election |
| RTD Director | No limit |

### Small Donor Committee to Candidate

| Office | Limit/cycle |
|---|---|
| Governor / Lt. Governor | $7,825 |
| Attorney General / SOS / Treasurer | $7,825 |
| State Senate / House | $3,100 |
| DA / CU Regent / SBE | $3,100 |
| County offices | $14,400 |
| School District Director | $25,000/election |

### Political Party to Candidate

| Office | Limit/cycle |
|---|---|
| Governor / Lt. Governor | $789,060 |
| Attorney General / SOS / Treasurer | $157,805 |
| State Senate / House | $20,500 |
| DA / CU Regent / SBE | $20,500 |
| County offices | $25,475 |
| School District Director | $2,500/election |

### Aggregate limits on party contributions

No person (other than a small donor committee) may contribute more than $4,675/calendar year to all party committees combined, of which no more than $3,875 may go to the state party. Small donor committees: $15,000 combined, $12,500 to state party.

**Corporate direct to candidates: PROHIBITED** — Art. XXVIII § 3(4)(a).
**Union direct to candidates: PROHIBITED** — Art. XXVIII § 3(4)(a).
Corporations and unions may establish separate segregated funds (PACs) and may contribute to political committees and issue committees.

**Home-rule exception**: Home-rule counties and municipalities may adopt their own contribution limits that differ from the state defaults listed above. TRACER includes sub-jurisdiction filings from these localities, so the state-level limits may not apply to all records in the bulk data. Per the [SOS limits page](https://www.coloradosos.gov/pubs/elections/CampaignFinance/limits/contributions.html): "Home Rule counties or municipalities may have their own contribution limits."

**`config.yaml` notes**: The flat `contribution_limits` schema uses statewide (governor) amounts as the primary values. See `laws.notes` entries for the full office-level breakdown.

## Itemization threshold

- **$20**: Contributions of $20 or more must be itemized with contributor name and address. (Art. XXVIII § 7; C.R.S. § 1-45-108)
- **$100**: Contributions of $100 or more from natural persons additionally require disclosure of employer and occupation. (Art. XXVIII § 7)
- **$250**: Threshold for electioneering communication contributor disclosure.
- **$1,000**: Major contributor report trigger — contributions of $1,000+ received within 30 days of an election must be reported within 24 hours. (C.R.S. § 1-45-108(2)(a))

Expenditures of $20 or more must also be itemized with payee name and purpose.

The `config.yaml` value `itemization_threshold: 20` reflects the base donor-identity disclosure threshold.

## Reporting periods and deadlines

Colorado uses two filing tracks based on activity level and election timing:

**Frequent filers** (election year, state-level):
- Pre-election biweekly reports starting first Monday in May through primary
- Monthly reports during mid-year period
- Pre-election biweekly reports from first Monday in September through general election
- Post-election report due 35 days after general election

**Infrequent/Quarterly filers** (odd years or lower activity):
- Quarterly reports due by the 15th day after each quarter ends

**Supplemental reports:**
- 24-hour major contributor reports ($1,000+ within 30 days of election)
- 48-hour independent expenditure reports

**Municipal filing:** 21st day before election, Friday before election, and 35 days after election.

**Election cycle definition:** Begins 31 days after a general election for the office, ends 30 days after the next general election. Cycle length varies: 2-year (State House), 4-year (Governor, SOS, AG, Treasurer, Senate, DA, county), 6-year (CU Regent, SBE).

Filing calendar: https://www.sos.state.co.us/pubs/elections/CampaignFinance/filingCalendar.html

**Electronic filing:** Mandatory via TRACER system. Authority: C.R.S. § 1-45-109(6)(a). Only registered or designated filing agents may file. Case-by-case exemptions available.

**Late filing penalty:** $50/day including weekends and holidays. (C.R.S. § 1-45-111)

## Prohibitions

- **Corporate direct contributions to candidates or parties: Prohibited.** Art. XXVIII § 3(4)(a). Corporations may establish separate segregated funds and contribute to political committees and issue committees.
- **Union/labor direct contributions to candidates or parties: Prohibited.** Same provision — Art. XXVIII § 3(4)(a). Unions may establish PACs funded by members.
- **Foreign source contributions: Prohibited.** Non-U.S. citizens, foreign governments, and foreign corporations without authority to transact business in Colorado. Art. XXVIII § 3(12).
- **LLC contributions:** Treated as contributions from individual members, attributed pro rata. Prohibited if LLC has elected corporate IRS treatment, has publicly traded shares, or has a foreign entity/non-citizen member. C.R.S. § 1-45-103.7.
- **Inter-committee restrictions:** Candidate committees, independent expenditure committees, issue committees, and small-scale issue committees may not contribute to other candidate committees.

## Public financing

Colorado has **no** state-level public financing program. Art. XXVIII and C.R.S. Article 45 do not establish matching funds, grants, or voucher programs.

Voluntary spending limits exist (Art. XXVIII § 4) but carry no public funding benefit. Current adjusted voluntary limits: Governor $3,945,300, AG/SOS/Treasurer $789,025, State Senate $141,975, State House/SBE/Regent/DA $102,500.

**Local exception:** Denver voters approved a Fair Elections Fund in 2018 (9:1 small-dollar matching for municipal candidates). This is a Denver municipal program, not relevant to state-level jurisdiction config.

## Known ambiguities / recent changes

- **CPI adjustment cycle**: Current limits effective 2023-02-15 per SOS CPF Rule 10.17. Next adjustment expected 2027. Amounts may change between now and then if interim rulemaking occurs.
- **LLC attribution rules**: SOS has progressively tightened LLC contribution disclosure requirements. Current rules require each member's name, address, attributed amount, and (if >$100) occupation and employer.
- **Small donor committee definition**: Must accept no more than $50/year per contributor. Art. XXVIII § 2(14). The $50 cap is not subject to CPI adjustment (constitutional text).

## Office-level or election-type variation

This is the single most significant structural feature of Colorado campaign finance law for schema modeling. Three distinct limit tiers exist:

1. **Constitutional limits** (Art. XXVIII): Statewide executives (Governor, AG, SOS, Treasurer) get higher limits; legislative and other state offices (Senate, House, DA, Regent, SBE) get lower limits; RTD directors have no limits.
2. **Statutory limits** (C.R.S. § 1-45-103.7): County offices, school district directors, and municipal offices each have their own limit schedules.
3. **Election vs. cycle basis**: School district and municipal limits are "per election" not "per cycle." Party contributions to parties are tracked per calendar year.

The `config.yaml` `laws.notes` entries document the full breakdown since the flat `contribution_limits` schema cannot represent all tiers.
