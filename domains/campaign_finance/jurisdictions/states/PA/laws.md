# Pennsylvania campaign-finance law notes

This file is narrative support for the PA `laws` block in `config.yaml`.

## Authoritative sources
- PA DOS campaign finance landing page: <https://www.pa.gov/agencies/dos/programs/voting-and-elections/campaign-finance>
- PA DOS reporting dates and penalties: <https://www.pa.gov/agencies/dos/programs/voting-and-elections/campaign-finance/reporting-dates>
- PA DOS campaign finance FAQ (contribution-limit and corporate/union guidance): <https://uat-content.pwpca.pa.gov/content/dam/copapwp-pagov/en/dos/resources/voting-and-elections/campaign-finance/CampaignFinanceFAQ.pdf>
- Pennsylvania Election Code campaign-finance provisions (25 P.S. §§ 3241-3260b): <https://www.legis.state.pa.us/cfdocs/legis/li/uconsCheck.cfm?txtType=HTM&yr=1954&sessInd=0&smthLwInd=0&act=320&chpt=16>

## Reporting rules
- DOS publishes annual, pre-primary, post-primary, pre-election, post-election, and 24-hour reporting schedules.
- Reporting Dates guidance states 24-hour reporting applies after the final pre-election/pre-primary report for contributions or independent expenditures of $500 or more.
- Late filing penalties are documented by DOS as `$20/day` for the first six late days, then `$10/day`, capped at `$250`.

## Contribution limits and prohibitions
- DOS FAQ states there is no dollar cap for an individual contribution to a candidate.
- DOS FAQ also states that aggregate cash contributions over `$100` are not permitted.
- DOS FAQ states corporations and labor unions (unincorporated associations) cannot make contributions or expenditures to candidates or political committees, while independent expenditures remain permitted.

## Amendment handling
- Source filing index uses `AMMEND` and `TERMINATE` fields (Y/N).
- Stage 1 evidence shows amendment status is filing-level and must be inherited to detail rows by joining detail `CampaignFinanceID` to filing `CampaignfinanceID`.
- This inheritance dependency is explicitly tracked in `config.yaml` `known_issues` for PA data sources.

## Data-quality caveats
- DOS yearly exports are archive-based and include a 2025 filename exception relative to the standard `{year}.zip` pattern.
- The portal currently exposes a "2002 Full Export" link target that resolves to `2022.zip`; this should be re-verified before automating historical backfills.
- Detail files may contain non-UTF8 bytes and require cp437 decoding for observed 2025 contribution and expenditure files.

## Open questions
- Confirm whether `pac_to_candidate` and `party_to_candidate` should stay modeled as `"unlimited"` in `config.yaml` or be constrained by additional statute-level interpretations not summarized in DOS FAQ guidance.
- Re-verify the campaign-finance data page link-target discrepancy (`2002` label resolving to `2022.zip`) before any automated historical download workflow.
