# Jurisdiction Config Schema

Each jurisdiction directory contains a `config.yaml` that describes available
data sources, applicable laws, and a legacy processing-status snapshot. The
config is machine-readable; companion files (`README.md`, `laws.md`,
`data_semantics.md`) provide human-readable context.

Within the campaign-finance region lifecycle, `config.yaml` is primarily the **Source Contract Translation** artifact. It captures machine-readable source facts and structured legal facts, but it is not the complete lifecycle record for a region. See [`docs/reference/specs/campaign-finance-region-lifecycle.md`](./campaign-finance-region-lifecycle.md).

The schema is enforced at runtime by
[`config_schema.py`](../../../domains/campaign_finance/jurisdictions/config_schema.py).
Its models reject unknown keys and validate supplied dates and status literals;
`load_jurisdiction_config` is the canonical reader. The canonical new-config
shape is [`_template/config.yaml`](../../../domains/campaign_finance/jurisdictions/_template/config.yaml).

## Example: Campaign Finance Domain

```yaml
# domains/campaign_finance/jurisdictions/states/EX/config.yaml
jurisdiction:
  name: "Example State"
  code: "EX"
  type: "state"  # federal | state | county | municipality
  fips: "00"
  parent: null    # for county/muni, reference parent jurisdiction

data_sources:
  - name: "Example bulk CSV portal"
    url: "https://example.state.gov/campaign-finance"
    bulk_download_url: "https://downloads.example.state.gov/campaign-finance/transactions.csv"
    api_base_url: null
    format: "csv"  # csv | api | web_portal | pdf | pipe_delimited
    auth_required: false
    update_frequency: "monthly"  # continuous | daily | weekly | monthly | quarterly | annual
    coverage:
      start_year: 2000
      covers_sub_jurisdictions: true
      office_levels:
        - state_senate
        - governor
      transaction_types:
        - contributions
        - expenditures
        - loans
    field_mappings:           # field_schema -> field_mappings (historical compatibility migration)
      source_contributor_name: "entity.name"
      source_amount: "transaction.amount"
      source_date: "transaction.date"
      source_committee: "committee.name"
    scraper: "./scraper/scrape.py"
    last_successful_pull: null  # required legacy placeholder; never advance after a pull
    last_verified_working: null # required legacy placeholder; never advance after a probe
    known_issues:
      - "Pre-2008 data has inconsistent employer fields"
      - "Municipal races sometimes missing district info"

  - name: "Example web portal fallback"
    url: "https://portal.example.state.gov/cf/"
    bulk_download_url: null
    api_base_url: null
    format: "web_portal"  # csv | api | web_portal | pdf | pipe_delimited
    auth_required: false
    update_frequency: "continuous"  # continuous | daily | weekly | monthly | quarterly | annual
    coverage:
      start_year: 1996
      covers_sub_jurisdictions: false
      office_levels:
        - municipality
      transaction_types:
        - contributions
        - expenditures
    field_mappings:
      tx_date: "transaction.date"
      tx_amount: "transaction.amount"
      tx_type: "transaction.type"
      committee_name: "committee.name"
      office_level: "jurisdiction.office_level"
    scraper: null
    last_successful_pull: null
    last_verified_working: null
    known_issues: []

laws:
  source_url: "https://example.state.gov/campaign-finance/law"
  last_verified: "2026-03-12"
  contribution_limits:
    individual_to_candidate: 5000
    pac_to_candidate: 5000
    corporate_direct: "prohibited"
    union_direct: "prohibited"
    party_to_candidate: null
  itemization_threshold: 50
  reporting:
    periods: ["quarterly", "pre-election"]
    electronic_filing_required: "required"
  public_financing: false
  # public_financing:
  #   type: "matching_funds"
  #   administering_agency: "Example State Election Board"
  notes:
    - "Capture office-level and election-type variation until Stage 3 rule-table model exists"

status:  # required inert compatibility placeholders; never advance operationally
  discovery: "unknown"
  scraper: "unknown"
  normalization: "unknown"
  entity_resolution: "unknown"
  last_full_update: null
```

## Key Fields

- **`data_sources[].field_mappings`** — Embedded per-source, not a separate file. Maps source column names to unified schema fields.
- **`data_sources[].known_issues`** — Document data quality gotchas discovered during scraping.
- **`data_sources[].scraper`** — Optional path to the jurisdiction-local scraper entrypoint. Must be a relative path inside that jurisdiction's `scraper/` directory; absolute paths and `..` segments are invalid.
- **`laws`** — Structured representation of jurisdiction-specific rules. Varies by domain (campaign finance limits, property tax rates, etc.).
- **`status`** — Legacy compatibility snapshot retained while existing configs
  are reconciled. It is not the owner of live monitoring, source maturity, or
  public coverage. Use `core.refresh_run` for observed operation,
  `sources.yaml` for L3 source maturity, and the coverage registry for public
  claims. Do not build a dashboard or status command from this block.

## Legacy Operational Snapshot Deprecation

### Compatibility baseline

The seven fields below predate the current lifecycle, L3, refresh, and coverage
owners. They remain part of the required input shape today: `DataSourceConfig`,
`StatusConfig`, and `JurisdictionConfig` declare them without defaults, and the
canonical template supplies every key. Existing tests prove that checked-in
configs load and that YAML dates resolve to `date` or `None`; `extra="forbid"`
continues to reject unknown fields. See
[`test_config_schema.py`](../../../domains/campaign_finance/jurisdictions/test_config_schema.py).

Current consumers also prevent claiming that these fields are removable yet.
In particular,
[`seed_registry.py::_best_last_verified_working`](../../../domains/campaign_finance/coverage/seed_registry.py)
still derives the coverage registry's readability copy from config, and some
jurisdiction-specific compatibility checks still read
`last_verified_working` or `status.scraper`. Those reads do not make the fields
authoritative; they are migration inventory.

### Field contract

Every field in this table is a **compatibility snapshot**, not present
operational, maturity, or public-coverage truth. A quoted `YYYY-MM-DD` string or
a YAML date scalar is date-only precision after typed loading; it never implies
a time of day, timezone, run identity, source-transition identity, or evidence
receipt. The four legacy `status` progress fields share the same
undifferentiated typed vocabulary from `StatusValueLiteral`:
`pending | in_progress | complete | working | partial | broken | unknown`.
Any token from that set may appear in any of the four fields; the token's
meaning comes only from the historical field label and never from a current
owner.

| Legacy field | Historical meaning and precision | `null` / placeholder meaning | Evidence it did and did not assert | Current authority or migration target |
| --- | --- | --- | --- | --- |
| `data_sources[].last_successful_pull` | Date on which a pull of that config source was believed to have succeeded; date-only and source-local. | `null` means no historical success date was recorded in this snapshot. It does not mean the current job has never succeeded. | At most asserted a historical success claim. It did not identify a `RefreshJob`, record `pull_status`, counts, errors, start/completion times, or establish current freshness. | First identify the matching `RefreshJob`. Observed attempts/results belong to `core.refresh_run`; cadence recency uses the job's branch-selected clock described below. |
| `data_sources[].last_verified_working` | Date on which that source/access path was believed to have been checked and working; date-only and source-local. | `null` means this snapshot has no recorded verification date. It does not mean the current L3 state is unknown, unverified, or failing. | At most asserted an uncited historical verification. It did not assert an L3 state, a transition, valid evidence, continuing availability, or a successful refresh. | The uniquely matching [`sources.yaml`](../../../sources.yaml) `source_id`, its `current_state`, and matching transition's `recorded_on` and `evidence_refs`, validated by [`core/keel_gate_l3.py`](../../../core/keel_gate_l3.py). |
| `status.discovery` | One coarse enum token from the shared `StatusValueLiteral` vocabulary summarizing perceived jurisdiction discovery progress. | This field is non-null in the current schema. In a new config it is an inert template placeholder, not a present assessment. | It did not distinguish acquisition-pattern research, source-contract maturity, legal/filing semantics, completeness intelligence, or supporting evidence. | The current discovery fact is lifecycle `discovery_maturity` only. Evidence may separately update other lifecycle fields when it proves those separate facts, but `status.discovery` is not a migration target for them and there is no token conversion. |
| `status.scraper` | One coarse enum token from the shared `StatusValueLiteral` vocabulary summarizing perceived scraper implementation or health. | This field is non-null in the current schema. In a new config it is an inert template placeholder, not current health. | It did not identify code wiring, a job, a run, outcome, evidence receipt, or the distinction between implemented, runner-wired, and operational. | No current field-specific/per-region canonical owner exists for a combined scraper status, so that specific current fact is `UNKNOWN`. Evidence may update the separate lifecycle `implementation_maturity` or `operational_maturity` facts; runner wiring remains the `RefreshJob` plan in [`core/refresh/runner.py`](../../../core/refresh/runner.py), and observed outcomes remain in `core.refresh_run`. There is no token conversion. |
| `status.normalization` | One coarse enum token from the shared `StatusValueLiteral` vocabulary summarizing perceived normalization progress. | This field is non-null in the current schema. In a new config it is an inert template placeholder, not a current pipeline claim. | It did not name covered fields, fixtures, live proof, history depth, completeness rules, or gap-detection evidence. | No current field-specific/per-region canonical owner exists for normalization status, so that specific current fact is `UNKNOWN`. Concrete evidence may update a separate owner only when it proves that owner's exact fact; no lifecycle field accepts a mechanical legacy-token conversion. |
| `status.entity_resolution` | One coarse enum token from the shared `StatusValueLiteral` vocabulary summarizing perceived entity-resolution readiness. | This field is non-null in the current schema. In a new config it is an inert template placeholder, not a current readiness claim. | It did not identify an entity-resolution contract, test population, quality result, loaded linkage, or lifecycle proof. | No current field-specific/per-region canonical owner exists for entity-resolution status, so that specific current fact is `UNKNOWN`. Concrete evidence may update an existing entity-resolution or lifecycle owner only when it proves that owner's exact fact; no token conversion is valid. |
| `status.last_full_update` | Date on which the jurisdiction pipeline was believed to have received a full update; date-only and jurisdiction-wide. | `null` means this snapshot has no recorded full-update date. It does not mean no current run or source pull exists. | At most asserted an ambiguous historical milestone. It did not identify a job, define "full," record an outcome/count/error, or establish current freshness. | Identify the correct `RefreshJob`; use `core.refresh_run` for observed attempts/results and the job's branch-selected cadence clock for recency. |

The lifecycle field names and fact kinds above are owned and typed by
[`lifecycle.py`](../../../domains/campaign_finance/coverage/lifecycle.py). Public
claim tier and evidence remain solely in the
[coverage registry](../research/coverage-registry.json), read by
[`registry.py`](../../../domains/campaign_finance/coverage/registry.py). No
legacy status token can upgrade either owner.

### Refresh identity and recency

A migration or comparison must resolve a config source or jurisdiction to the
correct `RefreshJob`; config path or source-list position is not a job identity.
The runner owns both wiring and the choice of cadence clock through
`cadence_last_pull_owner(job)` and `_select_latest_pull_at`:

- When `job.refresh_history_key` is present, recency is the maximum
  `core.refresh_run.completed_at` for that key among the runner-owned successful
  cadence statuses. Individual run facts remain that row's `pull_status`,
  `started_at`, `completed_at`, `inserted_count`, and `error`.
- Otherwise recency is `MAX(core.data_source.last_pull_at)` for the job's exact
  `domain`, `jurisdiction`, and `data_source_names`.

These branches are not interchangeable. In particular,
`last_successful_pull` and `last_full_update` cannot choose a branch or supply a
missing current timestamp merely because their legacy date is populated. See
the exact owner table and freshness rules in
[`campaign-finance-region-lifecycle.md`](./campaign-finance-region-lifecycle.md#authority-and-inheritance).

### Reader contract

During this deprecation phase:

- `load_jurisdiction_config` must continue to accept checked-in populated legacy
  dates, explicit `null` date placeholders, and valid quoted or YAML date
  scalars. Supplied dates and status values remain typed and invalid values must
  fail; `extra="forbid"` remains in force.
- All seven keys remain required. A newly created config must retain the keys
  shown by `_template/config.yaml`. Use `null` for each legacy timestamp unless
  traceable historical snapshot data is being preserved. Copy the template's
  valid status values only as inert compatibility placeholders; do not infer
  current progress to choose more favorable tokens.
- Reading a value for legacy compatibility is allowed. A reader must not treat
  it as fallback evidence when a current owner is absent or `UNKNOWN`.

This required-key rule is a statement about the current typed boundary, not a
claim that the fields remain desirable.

### Writer contract

An **operational write** is any update to a legacy value prompted by a source
probe, pull, refresh result, pipeline milestone, maturity judgment, health
change, or public-status change. All new operational writes are prohibited.
Writers must also not backfill legacy fields from a current owner.

Ordinary edits to config-owned structural source and legal facts remain allowed:
for example source identity and URLs, format, cadence, coverage boundaries,
field mappings, scraper path, known issues, and the structured `laws` block.
Preserving an already-recorded legacy value while making such an edit is not an
operational write. Moving an existing config without changing its snapshot is
also allowed.

### Mismatch and missing identity

Current authorities always win. A legacy value must never upgrade, override,
or supply an absent or `UNKNOWN` current fact. If a legacy snapshot differs from
its identified current owner, report **deprecation drift** with both paths and
the canonical owner; that drift does not invalidate an otherwise owner-only
projection and is not the cross-owner duplicate-refusal case defined for
current authorities.

A migration or comparison must stop rather than guess when it cannot uniquely
map:

- a config data source to one `sources.yaml` `source_id`;
- a config source or jurisdiction to one `RefreshJob` and its clock branch; or
- a config jurisdiction to the applicable lifecycle and coverage-registry
  identity, including parent inheritance where applicable.

Resolution requires evidence at the named owner. Do not select by list order,
substring similarity, newest timestamp, or most favorable value. Do not copy
the winning value back into config, and do not copy it into another readability
duplicate such as coverage-registry `best_last_verified_working`.

### Transition gates

There is no calendar-date removal promise. The gates are behavioral:

1. **Required to optional.** Legacy keys may become optional only in one
   coordinated, versioned change after all readers, writers, generators,
   templates, tests, readability duplicates, and production consumers have
   moved to the named current owner or removed their dependency, the typed
   reader accepts omission while preserving strict validation when values are
   supplied, and the canonical template and new-writer guidance omit the keys.
   Until all conditions hold, new configs retain every key. This transition is
   currently blocked by known readers and duplicates: `seed_registry.py`
   derives coverage-registry `best_last_verified_working` from config
   `last_verified_working`; `registry.py`, `render_summary.py`, and
   `tests/keel/test_gate_l14.py` still consume that readability duplicate;
   `jurisdictions/states/IN/scraper/test_init.py` still asserts
   `status.scraper`; and `jurisdictions/states/GA/scraper/download.py` still
   branches on `last_verified_working`.
2. **Deprecation window.** Once optional, the reader continues accepting old
   populated values and explicit `null` placeholders. Current owners still win,
   and operational writes remain prohibited.
3. **Removal.** Rejecting or deleting the fields requires an inventory proving
   that no checked-in config and no code or test reader needs them, plus an
   explicit versioned migration decision and value-based compatibility tests.

Repository-wide factual config rewrites and consumer migrations are separate
work. They must not be bundled into a documentation or schema-boundary change.
The non-blocking migration inventory is fixed for this contract: migrate each
jurisdiction-specific verification check from `last_verified_working` to its
uniquely identified L3 evidence owner, then either remove or explicitly rename
coverage-registry `best_last_verified_working` as a non-authoritative
readability duplicate in a separate versioned migration decision.

---

## Structured Contribution-Limit Rules: Contract (Stage 2 Decision)

This section supersedes the earlier "Laws Schema: Future Direction (Stage 3
Research Spike)" sketch. It is the source-grounded contract text produced by the
Stage 2 research/specification pass. Its evidence base is the Stage 1 audit
[`docs/reference/research/artifacts/2026_08_22_legal_variation_owner_audit.md`](../research/artifacts/2026_08_22_legal_variation_owner_audit.md)
(dimensions L1–L23, S1–S14, and the nine Open Questions), whose specimen
citations are not restated here except where a decision turns on one.

Stage 2 changes only this spec. It does not touch
[`config_schema.py`](../../../domains/campaign_finance/jurisdictions/config_schema.py),
any jurisdiction `config.yaml`, any loader, any migration, or any test. See
"Out of Scope for Stage 2" below.

### Decision: **refine**, and keep the fact inside the existing owner

The `campaign_finance.contribution_limit_rules` direction is **accepted with
refinements**, not rejected and not accepted as-is. Four refinements are load-
bearing and are specified below: (1) a `limit_basis` dimension replaces the
misleading `limit_per_election` column name; (2) an `explicit-unknown` value
state distinct from both "applies to all values" and "no statutory limit";
(3) per-rule `source_citation`, `effective_date`, and `sunset_date` semantics
separated from block-level `laws.last_verified`; (4) a single shared
`office_level` vocabulary bound to two separate fields.

Backward compatibility is preserved throughout: the flat `laws.contribution_limits`
block stays required and unchanged, and the structured rules are additive on top of
it. The refined rules live as **additive seed data inside the existing `laws`
block**, validated by the existing owner
[`config_schema.py::load_jurisdiction_config`](../../../domains/campaign_finance/jurisdictions/config_schema.py)
over each jurisdiction `config.yaml`. This is the seam the SSOT registry already
assigns to that owner: *"Keep source URLs, formats, coverage, cadence
expectations, field mappings, and structured source/legal facts here"*
([`docs/reference/ssot-registry.md:12`](../ssot-registry.md)). Concretely, the
implemented shape is an **optional** `laws.contribution_limit_rules: list[…]`
key inside `LawsConfig`.

**Rejected: a parallel legal-rule registry** (a new JSON/YAML store, a new
registry module, or a new SSOT row). Grounds: (a) the SSOT registry already
assigns structured legal facts to the config owner; (b) a second store of the
same facts would immediately fall under the lifecycle spec's duplicate-mismatch
refusal rule
([`campaign-finance-region-lifecycle.md`](./campaign-finance-region-lifecycle.md#duplicate-mismatch-rule),
"Duplicate-mismatch rule"), turning every drift into a refused projection; (c)
the `laws` block is already the designated seed for the rule table, so a separate
registry would need a migration away from an already-specified seam.

**Rejected for Stage 2: creating the PostGIS table, its loader, or any config
rewrite.** The `campaign_finance.contribution_limit_rules` table, the YAML→row
loader, and the per-jurisdiction seed migrations are **future, unbuilt** work.
A Stage 2 repo scan found only the fail-closed schema test outside documentation
and planning artifacts. The follow-up schema stage has since implemented the
typed config field, but there is still no runtime table consumer, `.sql`
definition, or checked-in `.yaml` seed. Stage 2 defined the **YAML seed shape and
its validation contract in prose only**; the table, loader, and migrations remain
follow-up Beads (see "Out of Scope for Stage 2").

### Rule identity and dimensions

**Row key: `jurisdiction_fips`, never `jurisdiction.code`.** The audit's identity-
key finding proves `jurisdiction.code` is not unique across the config tree
(`states/LA` → `code: LA`, `fips: 22` = Louisiana; `cities/LA` → `code: LA`,
`fips: 06037` = Los Angeles), and it is not the lifecycle/coverage identity
namespace (those rows are `CA_LOS_ANGELES`, `PA_PHILADELPHIA`, …). Because the
rule list is nested inside one jurisdiction's `config.yaml`, individual seed
rules do **not** repeat a jurisdiction key; the future table's `jurisdiction_fips`
column is populated by the loader from the enclosing config's `jurisdiction.fips`
(`06`, `13`, `06037`, …), never from `jurisdiction.code`. Nothing a config author
writes can therefore set a wrong or ambiguous key.

Each rule carries these dimension fields. A dimension that is **omitted or
`null` means "applies to all values of that dimension"** — the sketch's original
semantic, preserved. This "all values" meaning is deliberately kept **separate
from the explicit-unknown value state** defined below (that separation is the
single most important refinement; see "Value semantics").

| Dimension | Controlled vocabulary (seeded; extend by spec change, not ad hoc) | Notes |
| --- | --- | --- |
| `donor_type` | `individual`, `pac`, `party_committee`, `corporation`, `union`, `small_donor_committee`, `small_contributor_committee`, `candidate`, `self`, `issue_committee`, `ie_committee` | Fixes L2: the flat five-slot set has no home for CO's small-donor-committee schedule or CA's small-contributor committee (squeezed into `pac_to_candidate` today). |
| `recipient_type` | `candidate_committee`, `party_committee`, `pac`, `issue_committee`, `ie_committee`, `ballot_measure_committee` | Fixes L3: today every flat field assumes recipient = candidate, so CO's party-aggregate cap and its candidate→candidate / IE→candidate transfer bans cannot be expressed. |
| `office_level` | initial canonical tokens enumerated in "One office vocabulary, two fields" below | Fixes L1; omitted/`null` still means all offices. |
| `election_type` | `primary`, `general`, `runoff`, `special`, `recall` | Fixes L4: GA publishes runoff caps as a separate column; CA treats primary/general/special as separate elections. |

#### One office vocabulary, two fields (S3 decision)

Stage 2 decides: **`data_sources[].coverage.office_levels` and the legal-rule
`office_level` draw from one shared, canonically-spelled vocabulary, but remain
two separate fields with two separate meanings and owners' semantics.**

The **initial canonical allowed-token list** is the union needed to represent
the eight audited specimens, after normalizing known spelling aliases, plus the
four legal tiers those specimens publish:

- office-specific tokens: `attorney_general`, `board_of_equalization`,
  `board_of_supervisors`, `borough_president`, `city_attorney`,
  `city_commissioners`, `city_council`, `controller`, `cu_regent`,
  `district_attorney`, `governor`, `insurance_commissioner`, `judicial`,
  `lieutenant_governor`, `mayor`, `public_advocate`, `register_of_wills`,
  `secretary_of_state`, `sheriff`, `state_board_of_education`,
  `state_controller`, `state_house`, `state_senate`, `state_treasurer`, and
  `superintendent_of_public_instruction`;
- jurisdiction/scope tokens: `citywide`, `county`, `municipal`,
  `school_district`, `special_district`, and `rtd`;
- legal-tier tokens: `statewide`, `statewide_except_governor`, `legislative`,
  and `other_office`.

This is a closed, seeded vocabulary: a newly researched office or legally
defined tier requires a spec change before it can appear in a structured legal
rule. Within the eight specimens, existing source-scope spellings
`comptroller` (NYC) and `city_controller` (LA) alias canonical `controller`, and
`state_assembly` (CA) aliases canonical `state_house`. `state_controller`
remains distinct because the CA specimen names that statewide office explicitly;
`controller` is the canonical municipal-office token. The broader 26-config
normalization remains follow-up work; until it lands, those legacy aliases can
remain in existing unvalidated `coverage.office_levels`, but a new legal rule
must use only the canonical list above.

- One vocabulary removes the drift the audit found: 34 uncontrolled tokens with
  three spellings of one municipal office family — `comptroller` (NYC),
  `controller` (PHL), `city_controller` (LA) — and split chamber naming
  (`state_house` CO/GA/NC vs `state_assembly` CA). The canonical spellings and
  aliases are enumerated above rather than left to each config author.
- Two fields, not one, because they answer different questions and are not
  required to agree: `coverage.office_levels` is a **source-scope** fact ("which
  offices this feed carries") owned as part of the source contract;
  legal-rule `office_level` is a **legal-scope** fact ("which office this cap
  applies to"). A feed may cover offices that share one cap, and a cap may name
  an office the feed does not label per row (S13: NC's transaction export has no
  office column at all).
- Coupling caveat, stated explicitly per Open Question 4: sharing the vocabulary
  couples a source-scope field to a legal field only at the *token-spelling*
  level, not at the required-ness or ownership level. That is the intended, low-
  risk coupling. **Normalizing the existing `coverage.office_levels` values across
  the 26 checked-in configs is a config-rewrite project and is out of scope for
  Stage 2** (see follow-up Beads); the new legal-rule `office_level` uses the
  canonical vocabulary from creation because it is additive.

### Value semantics: amount, basis, and the five states

The flat scalar (`ContributionLimitValue = StrictInt | "unlimited" |
"prohibited" | None`,
[`config_schema.py:17`](../../../domains/campaign_finance/jurisdictions/config_schema.py))
carries no basis unit and overloads `None` across three incompatible meanings
(audit L5, L12). The refined rule replaces the sketch's single
`limit_per_election NUMERIC` / `banned BOOLEAN` / `unlimited BOOLEAN` triple with
a discriminated **`limit_status`** plus an amount and a basis:

| `limit_status` | `limit_amount` | `limit_basis` | Meaning | Audit dimension |
| --- | --- | --- | --- | --- |
| `numeric` | required (integer USD) | required | A dollar cap applies. | L1, L5 |
| `prohibited` | omitted | omitted | This donor→recipient combination is banned. Note the exception if one exists (NC corporate prohibition is subject to segregated-fund exceptions in 163-278.19; the exception rides in `metadata`, see below). | L10 |
| `unlimited` | omitted | omitted | Statute **affirmatively removes** the cap for this combination. Requires the exempting provision in `source_citation` (NC party per `163-278.13(h)`; NC candidate/spouse self-funding per `163-278.13(d)`). | L11 |
| `no_statutory_limit` | omitted | omitted | The governing statute contains **no cap provision** for this combination. Distinct from `unlimited`: nothing was removed and nothing was set (CA `party_to_candidate`, "No explicit party-to-candidate limit in the Political Reform Act"). | L12(b) |
| `unknown` | omitted (never a placeholder number) | omitted | **Not yet researched.** The `explicit-unknown` state. Requires a `note` naming the gap and the research owner (PHL's five `null` limits). | L12(a), L13 |

`limit_basis` controlled vocabulary (required only when `limit_status:
numeric`): `per_election`, `per_cycle`, `per_calendar_year`. This resolves Open
Question 1 by **naming the basis instead of normalizing amounts**: CO's per-cycle
$725 and NC's per-election $6,800 stay the numbers the statute states, and the
column is no longer mis-named `limit_per_election`. Normalizing per-cycle amounts
to a per-election basis would fabricate numbers no statute publishes, so it is
rejected. The `exempt` / no-cap cases are carried by `limit_status`
(`prohibited` / `unlimited` / `no_statutory_limit`), not by a basis token, so
"exempt/no-cap" is representable without inventing a basis for a rule that has no
amount.

The five `limit_status` values, ordinary numeric limits, `prohibited`,
`unlimited`, exceptions, and aggregation/local-override notes are therefore
**mutually understandable**: a consumer reads `limit_status` first and never has
to guess what a bare `null` meant.

#### The explicit-unknown state, and why it reuses an in-repo precedent

`unknown` is the direct answer to the audit's Open Questions 2 and 3 and to the
sketch's L12 collision (the sketch spent `NULL` on "applies to all values of that
dimension"). It reuses the tri-state precedent already in the repo:
[`registry.py::CoverageRegistryRow.ie_coverage_available`](../../../domains/campaign_finance/coverage/registry.py)
is `bool | None` where *"None = not yet determined"* is documented and load-
bearing (the API returns `null` IE totals rather than misleading zeroes). The
legal contract adopts the same discipline: `unknown` means "not yet determined",
never "zero", never "no limit", never "all values". PHL — which has **no checked-
in `laws.md`** and five `null` flat limits — becomes expressible as five
`limit_status: unknown` rules, each with a `note` pointing at the deferred
Board-of-Ethics research, instead of today's overloaded `null`.

**`itemization_threshold` placeholder (L13) — named, not fixed here.** PHL is
forced to publish `itemization_threshold: 50  # placeholder pending PHL Board-of-
Ethics research` because
[`LawsConfig.itemization_threshold`](../../../domains/campaign_finance/jurisdictions/config_schema.py)
is a required non-nullable `StrictInt` — a structural owner publishing a
fabricated legal number. The correct fix is the same explicit-unknown pattern
(make the field accept an unknown state), but that changes `LawsConfig`'s
required-key shape, which the "Transition gates" discipline above treats as a
coordinated, versioned change. Stage 2 therefore **records the intended fix and
its mechanism** and defers the schema change to a follow-up Bead; PHL keeps its
placeholder `50` until then, flagged here as a known fabricated value with a named
fix path.

### Citation and date semantics

Four distinct date facts, deliberately not conflated:

| Field | Scope | Meaning | Required? |
| --- | --- | --- | --- |
| `laws.last_verified` | whole `laws` block (existing field, [`config_schema.py:79`](../../../domains/campaign_finance/jurisdictions/config_schema.py)) | A **research** date: when a human last re-verified the block against sources. Never a legal effectivity date. | existing `date \| None` |
| rule `effective_date` | one rule | The date the known legal status **took effect** (CO amounts "effective 2023-02-15"; CA "effective 2025-01-01"; GA adopted 2023-03-27). It is never a research-observation date. | required for `numeric`, `prohibited`, `unlimited`, and `no_statutory_limit`; forbidden for `unknown` |
| rule `sunset_date` | one rule | The date the known rule **ceased to apply** (repeal/sunset). | optional for known statuses; omitted/`null` = currently in effect; forbidden for `unknown` |
| rule `research_observed_date` | one `unknown` rule | A **research** date: when the unresolved state was confirmed against the cited repository/source evidence. It makes the age of a gap queryable without pretending to know legal effectivity. | required for `unknown`; forbidden for every known legal status |

- **Open-ended current rules:** omit `sunset_date`.
- **Repealed / sunset rules:** set `sunset_date` and **keep the row**, so
  bitemporal queries ("what was the limit on election day 2022?") stay answerable.
  NC's public-financing sections "repealed effective July 1, 2013" (L7) is a
  sunset, not an absence, and is distinct from GA's "never existed".
- **Per-rule `source_citation` is required when a structured rule is supplied.**
  Block-level `laws.source_url` is one URL for the whole block, but individual
  rules cite different provisions — CO cites six distinct authorities (Art. XXVIII
  § 3(4)(a), § 7, § 3(12), C.R.S. § 1-45-103.7, § 1-45-108(2)(a), § 1-45-111)
  under one `source_url`; NC cites eight `163-278.*` provisions (L9). The sketch
  already declared `source_citation TEXT NOT NULL`; this contract keeps that.
  For a known status, the citation must identify the governing legal authority.
  For `unknown`, it must instead identify the concrete evidence that the current
  owner carries an unresolved value (for example the exact config field plus the
  dated audit); it must not masquerade as a legal citation and must be replaced
  with legal authority when research resolves the rule.
- **Public-financing carve-outs:** fine-grained public-financing *program*
  semantics (NYC's 8:1 match on the first $250, participating-vs-non-participating
  status, SF/LA match ratios — audit L17) stay with `laws.public_financing`
  (`PublicFinancingConfig`) and are a **separate** future extension, not absorbed
  into `contribution_limit_rules`. Where a *contribution limit itself* is
  conditioned on program participation, the rule carries a `note` and the tiered
  distinction is deferred; the contribution-rule table does not model match ratios.
- **Jurisdiction-specific exceptions** (exemptions, aggregation, prohibitions
  beyond donor class — L19/L20/L21) land in the rule's `metadata`/`notes` escape
  hatch with their own citation, described next.

### Exceptions, aggregation, and local overrides (audit decision-list item 6)

- **`local_override_allowed` — one optional typed boolean flag (L18).** CO's bulk
  TRACER feed carries sub-jurisdiction rows whose applicable limits are set by a
  home-rule locality, not the state, and `coverage.covers_sub_jurisdictions:
  true` makes the mismatch live in loaded rows. Because this has a direct data-
  correctness consequence, it earns a typed marker (default `false`) rather than
  prose. It records only that a state-default rule *may* be locally overridden; it
  does not itself carry the override amount (there is currently no CO-municipality
  config to hold that — Open Question 5, deferred).
- **`metadata` escape hatch for L19–L21.** Exemptions/carve-outs (GA self-and-
  family `21-5-41(g)`, NC candidate/spouse `163-278.13(d)`), aggregation/
  attribution rules (GA affiliated-entity aggregation `21-5-41(c)`, CO LLC pro-
  rata attribution C.R.S. § 1-45-103.7), and prohibitions beyond donor class
  (CO foreign-source ban, GA anonymous/blackout rules, NC straw-donor rules) land
  in `metadata`. Each item has a required free-text `description` carrying the
  carve-out prose and a required `source_citation` carrying its governing authority.
  The rule-level `metadata` field is optional and defaults to an empty list (`[]`)
  when omitted; omission means the rule has no recorded carve-out, not that its
  metadata state is unknown. Items are machine-**attached** to the specific rule
  (an improvement over today's block-level prose) but not machine-**enforced** in
  Stage 2. Promotion of any of these to a typed field is a follow-up Bead once
  evidence broadens, with the audit as the inventory.

### Backward compatibility

- **Flat `laws.contribution_limits` stays required and unchanged.** The five
  scalar fields in `ContributionLimitsConfig` remain exactly as they are, so all
  26 checked-in non-template configs — including PHL's all-`null` block — keep
  loading. `test_config_schema.py::test_load_jurisdiction_config_loads_each_pilot`
  continues to pass unchanged.
- **The structured rule seed shape is optional.**
  `LawsConfig.contribution_limit_rules` is an optional list, so a config that
  omits it remains valid. When supplied, its closed vocabularies and per-status
  field requirements are enforced by the canonical Pydantic reader.
- **`extra="forbid"` remains the reader discipline.** Stage 2 deliberately did
  not edit `config_schema.py`, so `contribution_limit_rules` was rejected during
  that contract-only stage. The follow-up schema stage has since enabled and
  typed this one field; other unknown `LawsConfig` keys remain invalid.
- **No Stage 2 item rewrites any jurisdiction `config.yaml` or `config_schema.py`.**

### Fit matrix: the eight representative jurisdictions

Each row shows the flat value that loads today, the legal variation the flat
form loses, and how the refined rule contract represents it **without any product-
code branching** (the loader reads a uniform rule list; there is no per-
jurisdiction `if`). Specimen citations are in the Stage 1 audit.

| Jurisdiction | Flat value (as checked in) | Variation flat form loses | Refined representation |
| --- | --- | --- | --- |
| **CO** | `individual 725`, `party 789060`, `itemization 20` | 13 office tiers; per-**cycle** vs per-**election** vs per-**calendar-year** basis; home-rule sub-jurisdiction overrides; party-aggregate cap | multiple `numeric` rules keyed by `office_level` + `limit_basis` (`per_cycle` statewide, `per_election` school/municipal); a `party_committee` recipient rule with `limit_basis: per_calendar_year`; `local_override_allowed: true` on the state-default rows |
| **GA** | `individual 8400` (all five = 8400) | runoff caps ($4,800 statewide / $1,800 all-other) as a separate election; statewide vs all-other office tier | rules split by `election_type` (`primary`/`general` = 8400, `runoff` = 4800) and by `office_level` (statewide vs other = 3300/1800) |
| **CA** | `individual 5500`, `pac 10200`, `party null` | governor / statewide-except-governor / legislative office tiers; small-contributor committee $10,200 (squeezed into `pac`); per-election basis; no PRA party limit | `office_level`-tiered `numeric` rules, `limit_basis: per_election`; a `small_contributor_committee` donor rule; `party_to_candidate` → `limit_status: no_statutory_limit` (not `null`) |
| **NC** | `party "unlimited"`, `corporate "prohibited"` | party value is a modelling compromise — statute *exempts* parties (`163-278.13(h)`); candidate/spouse self-funding also unlimited; corporate prohibition has segregated-fund exception | party rule → `limit_status: unlimited` with `source_citation: G.S. 163-278.13(h)`; a `self` donor rule → `unlimited` per `163-278.13(d)`; corporate rule → `prohibited` with the `163-278.19` exception in `metadata` |
| **NYC** | `individual 2000`, `public_financing matching_funds` | citywide $2,000 / borough-president $1,500 / council $1,000 office tiers; 8:1 match participation semantics | `office_level`-tiered `numeric` rules; match-ratio/participation semantics stay in `public_financing` (not in the rule table), noted on the rule |
| **PHL** | all five limits `null`; `itemization 50` (placeholder) | no `laws.md` exists; limits genuinely not researched; itemization threshold fabricated | five `limit_status: unknown` rules each with a `note` naming the Board-of-Ethics research gap; `itemization_threshold` fix deferred (required-key transition), placeholder flagged |
| **SF** | `individual 500`, `public_financing matching_funds` | per-office variation ("flattened law schema cannot fully encode per-office variation yet") | `office_level`-tiered `numeric` rules; SF Ethics match program stays in `public_financing` |
| **LA** | `individual 900`, `public_financing matching_funds` | per-office variation; amounts "indexed and adjusted periodically" | `office_level`-tiered `numeric` rules; indexation recorded as a re-verification note; LA City Ethics match program stays in `public_financing` |

Worked YAML seed examples (illustrative shape only — no config is edited in
Stage 2):

```yaml
# GA runoff as a separate election_type — no product-code branch needed
laws:
  contribution_limits: { individual_to_candidate: 8400, ... }   # flat block unchanged, still required
  contribution_limit_rules:                                     # optional additive seed validated by LawsConfig
    - donor_type: individual
      recipient_type: candidate_committee
      office_level: statewide
      election_type: primary            # primary and general require separate explicit rows
      limit_status: numeric
      limit_amount: 8400
      limit_basis: per_election
      effective_date: "2023-03-27"
      source_citation: "O.C.G.A. § 21-5-41(k); Commission notice 2023-03-27"
    - donor_type: individual
      recipient_type: candidate_committee
      office_level: statewide
      election_type: general
      limit_status: numeric
      limit_amount: 8400
      limit_basis: per_election
      effective_date: "2023-03-27"
      source_citation: "O.C.G.A. § 21-5-41(k); Commission notice 2023-03-27"
    - donor_type: individual
      recipient_type: candidate_committee
      office_level: statewide
      election_type: runoff
      limit_status: numeric
      limit_amount: 4800
      limit_basis: per_election
      effective_date: "2023-03-27"
      source_citation: "O.C.G.A. § 21-5-41(k); Commission notice 2023-03-27"

# NC exempt party + PHL explicit unknown — two honest non-numeric states
    - donor_type: party_committee       # NC: statute exempts parties from the cap
      recipient_type: candidate_committee
      limit_status: unlimited           # affirmative exemption, not "null"
      effective_date: "2013-12-01"
      source_citation: "N.C.G.S. § 163-278.13(h)"
    - donor_type: individual            # PHL: not yet researched
      recipient_type: candidate_committee
      limit_status: unknown             # explicit-unknown, never a placeholder number
      note: "PHL local limits not yet captured; see docs/reference/research/phl_campaign_finance_contract_2026_04_25.md"
      research_observed_date: "2026-08-22" # research date, never legal effectivity
      source_citation: "domains/campaign_finance/jurisdictions/cities/PHL/config.yaml laws.contribution_limits.individual_to_candidate; Stage 1 audit 2026-08-22"
```

## Source-Semantics Boundary (Stage 2)

Structured **source** facts stay in the existing config contract and are **not**
absorbed into `contribution_limit_rules`. The legal-rule contract answers "who may
give how much to whom"; the source contract answers "how to read this feed". These
are orthogonal owners with orthogonal lifecycle-maturity axes
(`legal_filing_semantics_maturity` vs `source_contract_maturity`), and mixing them
would recreate the duplicate-mismatch problem the rejected parallel registry has.

The following remain owned by `DataSourceConfig` / the source contract, unchanged
by Stage 2, and must not move into `contribution_limit_rules`:
`data_sources[].field_mappings` (source-column → unified-field), source meaning,
source coverage scope, `format`, `update_frequency`, and known source caveats
(`known_issues`).

### Disposition of the audit's source/semantic dimensions S1–S14

Per the Stage 1 audit, dimensions S1–S14 are `data_sources[]`-owned facts that
today live only in `data_semantics.md` prose or in untyped `dict`/`list[str]`
fields. Stage 2 **defers all of S1–S14 to a named source-semantics follow-up**,
for the reason the audit gives (Rank 2): the legal dimensions have a declared
target shape and eight worked specimens, while the source dimensions have neither,
and S3 alone (34 tokens, three "controller" spellings across 26 configs) is a
vocabulary-normalization project, not a contract paragraph. The follow-up boundary
is narrow and named: extend `DataSourceConfig` (or a sibling `data_semantics`
block), not `contribution_limit_rules`.

First candidates for that follow-up, highest-value first, because each has a closed
or near-closed vocabulary or a proven correctness consequence:

- **S4 — canonical transaction-type vocabulary.** Already exactly four tokens
  across all eight specimens (`contributions`, `expenditures`, `loans`,
  `independent_expenditures`); the cheapest controlled-vocabulary win.
- **S6 — date format + timezone per source.** Two of eight timezones are self-
  declared *assumptions* (CO assumed America/Denver, GA assumed America/New_York);
  encoding them is a correctness fix, not documentation.
- **S8 — amendment / supersession semantics.** GA's loader hard-codes
  `amendment_indicator='N'` because the export carries no amendment flag, while CO
  has an explicit `Amended = Y` filter rule; the contract must capture the five
  distinct per-source contracts.

The legal-rule contract must **not** absorb S5–S14 source-parsing, date/timezone,
amendment, row-shape/quarantine, or portal-navigation semantics: those are facts
about *reading a specific feed*, they vary per source rather than per statute,
they belong to a different maturity axis, and (per S13, NC has no office column)
they are sometimes the evidence path *for* a legal dimension rather than the legal
dimension itself. Also note S14 (dataset-scope caveats currently filed under
`laws.notes` in SF/LA) is a **source-scope** fact misfiled in the legal block; the
follow-up moves it to the source contract, and Stage 2 does not.

## Facts Excluded From This Contract (owned elsewhere)

Stage 2 must not absorb any of the following into the legal or source-semantics
contract. Each is cross-referenced to its owner in
[`campaign-finance-region-lifecycle.md`](./campaign-finance-region-lifecycle.md#fact--canonical-owner--readvalidation-path--fact-kind):

- **Lifecycle maturity (judgment)** — `acquisition_pattern`,
  `discovery_maturity`, `source_contract_maturity`,
  `legal_filing_semantics_maturity`, `implementation_maturity`,
  `operational_maturity`, `completeness_intelligence_maturity`,
  `civics_candidacy_status`, `main_blocker`, `updated_at`. Owned by
  `implemented-region-lifecycle.json` /
  [`lifecycle.py`](../../../domains/campaign_finance/coverage/lifecycle.py).
  Adding legal dimensions is *evidence* that could justify a maturity change; it
  is never itself a maturity change, and this contract must not compute or infer
  those fields.
- **Public coverage tier / evidence (judgment/observed)** — `tier`,
  `evidence_summary`, `evidence_date`, `operational_reason`, `next_action`,
  `loaded_count`, `expected_count`, `ie_coverage_available`,
  `parent_jurisdiction_code`, `municipal_audit_decision`, `municipal_portal_url`.
  Owned by `coverage-registry.json` /
  [`registry.py`](../../../domains/campaign_finance/coverage/registry.py).
- **L3 source-maturity state and transition evidence** — `sources.yaml`
  `current_state`, transition `recorded_on` / `evidence_refs`, validated by
  [`core/keel_gate_l3.py`](../../../core/keel_gate_l3.py). The lifecycle floor
  stands: a `config.yaml` `data_sources[]` entry alone supports at most
  `encoded`, never `verified`.
- **Runner wiring and observed refresh history** — the `RefreshJob` plan in
  [`core/refresh/runner.py`](../../../core/refresh/runner.py), `core.refresh_run`,
  and `core.data_source.last_pull_at` via `cadence_last_pull_owner`.
- **Derived status views** — `derive_implemented_jurisdiction_codes()` and any
  status command are derived views, never replacement registries.
- **Legacy `status.*` and `last_*` compatibility snapshots** — governed by
  "Legacy Operational Snapshot Deprecation" above; the `laws` extension is inside
  the permitted-edit envelope and must not touch the seven legacy fields.

The lifecycle spec's **duplicate-mismatch rule** applies to anything this contract
adds: if the extended contract restates a value another owner holds, do not emit
the disputed value — report the mismatch and name the canonical owner. The audit
confirms every dimension L1–L23 and S1–S14 (except S3's shared `office_level`
vocabulary, handled explicitly above) is a fact **no current owner holds**, which
is precisely how this extension stays clear of that rule.

## Out of Scope for Stage 2

Stage 2 produces contract text only. It does **not** do, and must not be read to
authorize, any of the following:

- no production schema migration and no `campaign_finance.contribution_limit_rules`
  PostGIS table;
- no YAML-to-row loader;
- no region `config.yaml` rewrites and no `config_schema.py` change;
- no product behavior change and no investigation query;
- no public coverage claim (pipeline code or loaded rows never authorize a claim);
- no parallel legal-rule registry.

Follow-up work uses this contract and the Stage 1 audit as its specification.
The schema-validation follow-up is complete; the remaining work stays in Beads:

1. **Completed:** add the optional `laws.contribution_limit_rules` field to
   `LawsConfig` with Pydantic validation of the vocabularies and the
   `limit_status`/`limit_basis` discriminant.
2. Create the `campaign_finance.contribution_limit_rules` table and the YAML→row
   loader (`jurisdiction_fips` populated from `jurisdiction.fips`).
3. Per-jurisdiction seed migration batches (CO, GA, CA, NC, NYC, PHL, SF, LA
   first), each preserving the flat block.
4. Make `itemization_threshold` accept an explicit-unknown state (a coordinated,
   versioned required-key transition per "Transition gates"), retiring PHL's
   placeholder `50`.
5. Normalize the `office_level` vocabulary across existing
   `coverage.office_levels` values in the 26 configs to the canonical spellings.
6. PHL Board-of-Ethics legal research to replace the `unknown` rows with real
   limits.
7. Source-semantics extensions for S1–S14, starting with S4/S6/S8, on
   `DataSourceConfig` (not on `contribution_limit_rules`).
