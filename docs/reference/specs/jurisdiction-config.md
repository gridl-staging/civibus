# Jurisdiction Config Schema

Each jurisdiction directory contains a `config.yaml` that describes available data sources, applicable laws, and processing status. The config is machine-readable; companion files (`README.md`, `laws.md`, `data_semantics.md`) provide human-readable context.

Within the campaign-finance region lifecycle, `config.yaml` is primarily the **Source Contract Translation** artifact. It captures machine-readable source facts and structured legal facts, but it is not the complete lifecycle record for a region. See [`docs/reference/specs/campaign-finance-region-lifecycle.md`](./campaign-finance-region-lifecycle.md).

A Pydantic model will enforce this schema at runtime (see implementation roadmap Stage 1).

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
    last_successful_pull: "2026-03-01"
    last_verified_working: "2026-03-10"
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

status:
  discovery: "complete"
  scraper: "working"
  normalization: "complete"
  entity_resolution: "partial"
  last_full_update: "2026-02-28"
```

## Key Fields

- **`data_sources[].field_mappings`** — Embedded per-source, not a separate file. Maps source column names to unified schema fields.
- **`data_sources[].known_issues`** — Document data quality gotchas discovered during scraping.
- **`data_sources[].scraper`** — Optional path to the jurisdiction-local scraper entrypoint. Must be a relative path inside that jurisdiction's `scraper/` directory; absolute paths and `..` segments are invalid.
- **`laws`** — Structured representation of jurisdiction-specific rules. Varies by domain (campaign finance limits, property tax rates, etc.).
- **`status`** — Processing pipeline status per jurisdiction. Used by monitoring and coverage dashboards.

---

## Laws Schema: Future Direction (Stage 3 Research Spike)

The `laws` block currently captures core constraints in a flat form that is stage-appropriate for template generation and quick review.
Stage 3 redesign targets a **relational rules table** in PostGIS — one row per rule, dimensions as columns:

```sql
-- campaign_finance.contribution_limit_rules
-- Each row = one rule for one (jurisdiction × donor_type × recipient_type × office_level × election_type) combination.
-- NULL in a dimension column means "applies to all values of that dimension."
-- Bitemporal: effective_date/sunset_date lets us query "what was the limit on election day 2022?"

jurisdiction_fips    TEXT NOT NULL
donor_type           TEXT          -- individual | pac | party | corporation | union | ...
recipient_type       TEXT          -- candidate_committee | party_committee | pac | ...
office_level         TEXT          -- governor | state_senate | state_house | local | NULL=all
election_type        TEXT          -- primary | general | runoff | NULL=all
limit_per_election   NUMERIC       -- NULL if banned or unlimited
banned               BOOLEAN
unlimited            BOOLEAN
effective_date       DATE NOT NULL
sunset_date          DATE          -- NULL = currently in effect
source_citation      TEXT NOT NULL
metadata             JSONB         -- escape hatch for jurisdiction-specific edge cases
```

The config.yaml `laws` block becomes **seed data** for this table — the law agent outputs YAML, human reviews it, loader inserts rows. Investigation queries ("did this donor exceed the limit?") become a simple parameterized SELECT on this table. The Stage 3 research spike finalizes the controlled vocabulary for each dimension column and the Pydantic model that validates the YAML → row mapping.
