# Minnesota campaign-finance law notes

This file is narrative support for the `laws` block in `config.yaml`.

## Authoritative source
- Minn. Stat. § 10A.27 (candidate and party-unit limits): `https://www.revisor.mn.gov/statutes/cite/10A.27`
- Minn. Stat. § 10A.20 (reporting cadence, filing, disclosure): `https://www.revisor.mn.gov/statutes/cite/10A.20`
- Minn. Stat. § 211B.15 (corporate contribution prohibitions and IE exceptions): `https://www.revisor.mn.gov/statutes/cite/211B.15`
- Minn. Stat. § 10A.322 (public subsidy / spending-limit agreement context): `https://www.revisor.mn.gov/statutes/cite/10A.322`
- MN CFB party-unit guidance: `https://register.cfb.mn.gov/filer-resources/self-help/contribution-and-spending-limits/party-units/`
- MN CFB committee/fund guidance: `https://register.cfb.mn.gov/filer-resources/self-help/contribution-and-spending-limits/committees-and-funds/`

## Contribution limits table
- Candidate limits vary by office under § 10A.27 subd. 1.
- Party-unit contribution limit is 10x office-level candidate limit under § 10A.27 subd. 2.
- PAC-to-candidate limits follow the same office-level framework as individual limits.
- `config.yaml` keeps a flattened contribution-limits object and documents office-level variation in notes.

## Itemization threshold
- `itemization_threshold: 200` is sourced from § 10A.20 disclosure/itemization context.

## Reporting periods and deadlines
- Minnesota reporting cadence varies by filer class and election year under § 10A.20.
- The current config period summary uses annual + pre-primary + pre-general.
- Electronic filing is required under the board system for covered filers.

## Prohibitions
- Corporate direct contributions are prohibited under § 211B.15.
- Board guidance distinguishes general-purpose entities from IE/ballot-question committees for source treatment.
- `union_direct` remains null in config pending legal interpretation of political-fund treatment.

## Public financing
- `public_financing` is represented as political-contribution-refund context in config.
- § 10A.322 provides statutory context for subsidy/spending-limit treatment.

## Known ambiguities / recent changes
- The flat schema cannot fully express office-level variation in limits.
- Union direct classification is intentionally left unresolved in config until legal review.

## Office-level or election-type variation
- Governor-level limits differ from legislative and other office classes.
- Party-unit multiplier depends on the underlying office-level candidate limit.
- Reporting requirements vary by election-year status and filer category.
