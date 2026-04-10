# Georgia Campaign Finance Laws

Narrative support for the `laws` block in `config.yaml`. Research date: 2026-03-14.

## Authoritative source

- **Georgia Ethics in Government Act (Commission-hosted statutory text PDF)**:
  - https://media.ethics.ga.gov/Commission/pdf/EthicsInGovernmentAct.pdf
- **Primary sections used from that statutory text**:
  - O.C.G.A. § 21-5-41 (campaign contribution limits; donor classes and office tiers)
  - O.C.G.A. § 21-5-34 (itemization threshold, CCDR timing, 2-business-day reporting)
  - O.C.G.A. § 21-5-34.1 (electronic filing requirement)
  - O.C.G.A. § 21-5-35 (session fundraising blackout)
  - O.C.G.A. § 21-5-30 (anonymous contribution prohibition, personal-use prohibition)
- **Commission contribution-limits notice** (adjusted dollar amounts adopted March 27, 2023 under § 21-5-41(k)):
  - https://ethics.ga.gov/contribution-limits/
- **Commission filing schedule** (2026 operational due dates):
  - https://ethics.ga.gov/filing-schedule/

## Contribution limits table

Georgia law applies limits in § 21-5-41 to contributions from a `person`, `corporation`, `political committee`, or `political party` to candidate committees. The Commission-adjusted amounts currently published are:

| Candidate class | Primary/General | Runoff |
|---|---:|---:|
| Statewide candidates (`§ 21-5-41(a)`) | $8,400 | $4,800 |
| All other candidates (`§ 21-5-41(b)`) | $3,300 | $1,800 |

`config.yaml` uses the statewide primary/general amount (`8400`) for flat donor-class fields (`individual_to_candidate`, `pac_to_candidate`, `corporate_direct`, `union_direct`, `party_to_candidate`) and carries office-level variation in `laws.notes`.

Union-specific language is not separately enumerated in § 21-5-41 contribution-cap text; this config normalizes unions under the same cap family as other donor entities and documents the assumption in `laws.notes`.

## Itemization threshold

`itemization_threshold: 100` is based on § 21-5-34(b)(1)(A)(ii)(I): itemized contributor identity fields are required when aggregate contributions from a contributor exceed $100 in an election cycle. Contributions up to that amount may be reported in aggregate.

## Reporting periods and deadlines

### Statutory cadence

Per § 21-5-34(c), CCDRs include periodic reporting tied to election timing and year-end windows, including election-period filings and additional reporting obligations.

### Operational schedule in current Commission guidance

The Commission filing-schedule page currently lists 2026 CCDR periods for all filers as:

- `January 1 – January 31` (due January 31)
- `February 1 – April 30` (due April 30)
- `May 1 – July 31` (due July 31)
- `August 1 – October 20` (due October 20)

Grace-period end dates are separately published on the same schedule page.

### Electronic filing requirement

- § 21-5-34.1: reports required by Article 2 are filed electronically unless a statute-specific exception applies.
- § 21-5-34(n): additional explicit electronic-filing trigger for persons/committees exceeding $25,000 in contributions/expenditures.

Given this statutory posture, `config.yaml` sets `electronic_filing_required: "required"` and documents threshold nuance in notes.

## Prohibitions

Statutory prohibitions/special constraints relevant to normalization include:

- **Anonymous contributions prohibited** (§ 21-5-30(a)).
- **Conversion of campaign funds to personal use prohibited** (§ 21-5-30(c)).
- **Session fundraising blackout** for General Assembly members, statewide elected officers, and related committees during legislative-session windows (§ 21-5-35).
- **Utility/regulated-entity contribution restrictions** in § 21-5-30.1 (public utility corporations, natural-gas marketers, electric membership corporations and affiliates).

## Public financing

No Georgia state public-financing matching-fund or grant program was identified in Chapter 5 campaign-finance provisions or Commission campaign-filing guidance pages used for this stage.

`config.yaml` therefore keeps `public_financing: false`.

## Known ambiguities / recent changes

- Commission-published adjusted limits currently reference the March 27, 2023 vote; monitor this page for future CPI-driven updates under § 21-5-41(k).
- Filing cadence changed in 2026 guidance (SB 199 implementation context) and should be re-verified each cycle against both statute and schedule-page updates.

## Office-level or election-type variation

Georgia contribution limits vary by office tier and election type:

1. Statewide (`§ 21-5-41(a)`) vs all-other offices (`§ 21-5-41(b)`).
2. Primary/general vs runoff caps.
3. Party-ticket/group support carve-out in § 21-5-41(j).

These variations are represented in narrative notes because the flat `contribution_limits` schema cannot encode all tiers directly.
