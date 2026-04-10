# Florida campaign-finance law notes

This file is narrative support for the FL `laws` block in `config.yaml`.

## Authoritative sources
- Florida Statutes Chapter 106 (Campaign Financing): <https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0106/0106.html>
- Section 106.08 (Contribution limits): <https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0106/Sections/0106.08.html>
- Section 106.07 (Reports; certification and filing): <https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0106/Sections/0106.07.html>
- Section 106.0705 (Electronic filing): <https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0106/Sections/0106.0705.html>

## Contribution limits (Section 106.08)
- Individual to candidate: Florida law sets tiered per-election limits by office class. As of the 2025 statutes, the statewide-office cap is $3,000 and the legislative/county/sub-county cap is $1,000. `config.yaml` stores $1,000 as the lower common cap.
- PAC to candidate: Political committees are subject to the same per-election candidate limits in Section 106.08(1)(a).
- Corporate and union direct contributions: Chapter 106 does not impose a categorical corporate or labor-union ban on direct candidate contributions; the same candidate contribution caps apply.
- Party to candidate: Section 106.08(2) sets aggregate caps from party executive and affiliated party committees (generally $50,000, with a higher $250,000 cap for statewide candidates). `config.yaml` stores $50,000 as the lower common cap.

## Itemization and disclosure thresholds
- Campaign treasurers must file reports under Section 106.07.
- Contributor detail requirements include employer/occupation disclosure thresholds for larger contributions; this package keeps `itemization_threshold: 100` as the operational baseline for detailed contributor disclosure handling.

## Reporting periods
- Section 106.07 requires regular quarterly reporting.
- Election-season reporting cadence increases, including weekly and, for division-level filers, daily windows approaching the general election.
- Filing officers issue schedules with exact reporting windows and due dates for each cycle.

## Electronic filing
- Section 106.0705 requires electronic filing for entities that file with the Division of Elections.
- Local filing-officer workflows may vary by filer category, but statewide/division filings are electronic.

## Public financing
- No statewide public-financing program is modeled in this package (`public_financing: false`).
