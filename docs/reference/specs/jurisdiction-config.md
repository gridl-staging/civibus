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

## Identity And Coverage Boundary

The config identity is exactly `(jurisdiction.type, jurisdiction.code)`. The
type is load-bearing: `state/LA` and `municipality/LA` are distinct even though
their code token is the same. `jurisdiction.name`, `jurisdiction.fips`, and the
package directory are attributes of that composite identity, not alternate
keys.

`GeographicJurisdictionTypeLiteral` is the closed geographic-subject set
`federal | state | county | municipality | school_district | special_district`.
Config acquisition identity uses the backward-compatible public name
`JurisdictionTypeLiteral`, whose authority-kind set adds `named_other` for a
source package owned by an explicitly named non-geographic filing authority.
This does not add `named_other` to geography. The coverage registry separately
types filing-authority references with the same authority-kind vocabulary.

The current schema types `jurisdiction.fips` and `jurisdiction.parent` only as
strings. They are compatibility/source-contract fields with these limits:

- `fips` does not carry an identifier kind. A state FIPS, county/county-
  equivalent GEOID, and place GEOID are different identifiers even when all are
  digits. Several municipality configs preserve county-shaped values, so
  `(type, code)` remains the only config identity and bare `fips` must not join
  to `core.jurisdiction`, coverage, civic, provenance, or route owners.
- `parent` is package/acquisition context expressed in config-code space. It is
  not `core.jurisdiction.parent_id` geographic containment and is not coverage-
  registry inheritance. Translation validates it against those owners when
  applicable but never copies it into them or lets it override them.
- `data_sources[].coverage.covers_sub_jurisdictions` says only that one source
  has some sub-jurisdiction scope. It does not identify every covered child,
  filing authority, office/contest class, transaction class, or completeness
  boundary and cannot alone authorize an inherited public claim.

Cross-owner translation therefore accepts `(namespace, kind, value)`, requests
one target kind, and refuses zero matches, multiple matches, kind mismatch,
contradiction, or a missing target slot. The coverage-registry translation
owner keeps `geographic_subject`, `filing_authority`, `acquisition_scope`,
`provenance_scope`, and `public_route` separate. It never infers a FIPS kind
from string length, config type, directory, or name. Operational/provenance
scope strings are exact owner-local values and are not reverse-parsed into
config or geography.

The target consolidated-city-county geography remains with the geography owner:
one proven coextensive geographic object with kind-qualified county-equivalent
and place identifiers. A city config carrying its surrounding county's GEOID is
not evidence of consolidation. Until the geography and translation owners can
represent and prove the mapping, translation refuses; config data remains
unchanged.

## Example: Campaign Finance Domain

```yaml
# domains/campaign_finance/jurisdictions/states/EX/config.yaml
jurisdiction:
  name: "Example State"
  code: "EX"
  type: "state"  # federal | state | county | municipality | school_district | special_district | named_other
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

The structured legal-rule, source-semantics, compatibility, and follow-up
contract continues in [Structured Contribution-Limit Rules](./jurisdiction_config_contribution_limit_rules.md).
