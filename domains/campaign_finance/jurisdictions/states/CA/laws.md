# California campaign-finance law notes

This file is narrative support for the laws block in config.yaml.

## Authoritative source
- FPPC campaign-rules pages for state candidate contribution limits and reporting guidance. [S1]
- California Political Reform Act statute text in Government Code sections governing disclosure and contribution-limit framework. [S2][S3]
- Secretary of State campaign/lobbying filing guidance for CAL-ACCESS operational context. [S4]

## Contribution limits table
FPPC publishes office-tiered per-election limits for the 2025-2026 cycle, including:
- Senate/Assembly and default city/county candidate tiers.
- Statewide-except-governor tier.
- Governor tier.
- Small-contributor-committee and party distinctions.

Because config.yaml currently stores a flattened contribution-limits object, office-tier nuance is represented in notes rather than a full tier matrix. [S1]

## Itemization threshold
Government Code section 84211 requires contributor identifying details at and above statutory thresholds, including name/address and occupation/employer details where applicable. Current CA config uses a 100-dollar itemization threshold consistent with this disclosure baseline. [S2]

## Reporting periods and deadlines
California filings include semi-annual and election-related reporting periods, with additional behavior by committee type and election context. CAL-ACCESS is the statewide filing surface for state-level candidates and committees. [S1][S4]

## Prohibitions
CA law and FPPC guidance include donor-class and use-of-funds constraints that affect how contribution-limit and committee semantics are interpreted in downstream models. Key prohibitions and carve-outs should continue to be tracked in config notes as statutes or regulations change. [S1][S3]

## Public financing
No statewide public-financing program is represented in the current CA stage-2 campaign-finance package contract.

## Known ambiguities and recent changes
- FPPC contribution-limit charts are cycle-specific and update over time; values in config must be re-verified each cycle.
- Office-tiered legal limits do not map cleanly to the current flattened config schema without losing detail.

## Office-level or election-type variation
CA limits vary by office class (for example governor versus statewide-except-governor versus legislative tiers) and election type (primary/general/special as separate elections). This variation remains narrative because the current schema does not encode a multi-tier limit matrix.

## Open questions
- Should the CA package encode the default city/county state-floor limits or statewide state-office limits in the flattened laws.contribution_limits fields?
- Should laws values be treated as point-in-time (cycle-stamped) metadata instead of static jurisdiction constants?

## Sources
- [S1] https://www.fppc.ca.gov/learn/campaign-rules/state-contribution-limits-and-voluntary-expenditure-ceilings/
- [S2] https://www.leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?article=2.&chapter=4.&division=&lawCode=GOV&part=&title=9.
- [S3] https://www.leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?chapter=5.&part=1.&lawCode=GOV&title=9
- [S4] https://www.sos.ca.gov/campaign-lobbying/helpful-resources/how-to-file-electronically
