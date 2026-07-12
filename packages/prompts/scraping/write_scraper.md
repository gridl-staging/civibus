# Write Scraper

**Consumer:** `agents/scraping/scrape_agent.py`

This prompt generates scraper code and tests for a single `data_sources` entry from a jurisdiction's `config.yaml`. It produces download or browser-automation scripts — not normalization, not ingest pipeline logic, and not schema transformation. The scraper's job is to retrieve raw source data exactly as the authoritative source provides it.

> **Legacy note:** Older docs reference `write_playwright_script.md`. That name is stale. This file (`write_scraper.md`) is the authoritative prompt for all scraper generation.

---

## Purpose

Given one `data_sources` entry from a jurisdiction `config.yaml`, generate:
1. A working Python scraper script that downloads or scrapes the data.
2. A representative test fixture under `scraper/test_data/`.
3. An automated test file that validates the scraper against the fixture.

The scraper must preserve raw-source fidelity — download the authoritative file or response as-is, emit scrape metadata, and avoid any schema transformation.

---

## Expected Input Format

The agent receives a single `data_sources[]` entry from the jurisdiction's `config.yaml`. The canonical schema for this object is defined in `docs/reference/specs/jurisdiction-config.md`. Do not redefine it here.

The prompt consumes these fields from the entry:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Human-readable source name |
| `url` | yes | Primary source URL |
| `bulk_download_url` | no | Direct download URL if different from portal |
| `format` | yes | `csv`, `api`, `web_portal`, or `pdf` |
| `auth_required` | yes | Whether authentication is needed |
| `update_frequency` | no | How often data changes |
| `coverage` | no | What data is covered (years, types, levels) |
| `field_mappings` | no | Source-to-schema field mapping |
| `known_issues` | no | Known data quality problems |
| `scraper` | no | Existing scraper path if already set in config |

**Fail closed:** If `name`, `url`, `format`, or `auth_required` is missing from the input, do not attempt to generate a scraper. Report the missing keys and stop.

---

## Expected Output Format

All generated scraper artifacts are **Python**. The Playwright language binding is `playwright` for Python (`pip install playwright`), not the TypeScript/Node.js version.

### Mode Selection

Choose the generation mode strictly from the `format` field:

| `format` value | Mode | Script path |
|---|---|---|
| `csv` | Direct download | `scraper/download.py` |
| `api` | Direct download (API client) | `scraper/download.py` |
| `web_portal` | Browser automation (Playwright) | `scraper/scrape.py` |
| `pdf` | **Fail closed** — escalate with note | No script generated |
| anything else | **Fail closed** — escalate with note | No script generated |

For unsupported or manual-only formats, do not generate a scraper. Instead, produce an escalation note explaining why automated scraping is not feasible and what human steps are required.

### Artifact Contract

Every successful run must produce exactly three artifacts:

1. **Scraper script** — at the path determined by mode selection above.
   - If `data_sources[].scraper` is already set in the config, first validate that it is a relative path rooted under the jurisdiction's `scraper/` directory. Reject absolute paths, any path containing `..`, and any normalized path that escapes `scraper/`.
   - Only after that validation passes, use the configured `data_sources[].scraper` path exactly as written.
   - If `data_sources[].scraper` is absent, use the default path from the table above and report the chosen path so the config can be updated to match.
   - **Fail closed:** if the configured `scraper` path is invalid or escapes the `scraper/` directory, do not generate files. Report the invalid path and escalate for a config fix.

2. **Test fixture** — under `scraper/test_data/`:
   - CSV/API mode: a sample response file with 20–50 representative records when possible (e.g., `scraper/test_data/sample_response.csv` or `scraper/test_data/sample_response.json`).
   - Web portal mode: a captured HTML page, JSON API response, or other raw response sufficient to exercise selectors, pagination, and parsing (e.g., `scraper/test_data/captured_page.html`).

3. **Test file** — `scraper/test_scraper.py`:
   - Runs against the saved fixture by default (no live network access).
   - Verifies the expected output shape (column names, record count, data types).
   - Includes a clearly marked live-verification test that is skipped by default and requires an explicit flag to run (e.g., `@pytest.mark.live`).

---

## Constraints and Politeness Rules

### Raw-Source Fidelity

- Download the authoritative file or API response as-is. Do not transform, filter, or reformat the data in the scraper.
- Emit scrape metadata alongside every run:
  - Source URL accessed
  - Run timestamp (UTC)
  - Record count or file count retrieved
  - File size (bytes)
  - Any warnings or anomalies encountered

### Retry and Error Handling

- Retry transient failures (network errors, timeouts, 5xx responses) with exponential backoff, up to 3 attempts.
- Fail immediately on 4xx client errors (except 429 Too Many Requests, which should be retried with backoff).
- Handle pagination termination: detect the last page and stop. Guard against duplicate pages and infinite loops.
- Handle empty result sets gracefully — log a warning but do not treat as an error if the source legitimately has no data for the query.
- Handle partial downloads: verify file integrity (expected size, row count, or checksum when available) before declaring success.

### Encoding and Malformed Data Handling

- Default to UTF-8 but detect and handle non-UTF-8 encodings (Latin-1, Windows-1252) common in government exports.
- Strip byte-order marks (BOM) when present.
- Handle inconsistent delimiters: detect the actual delimiter rather than assuming comma.
- Handle header drift: verify that column headers match expectations and log a warning if they differ from the field_mappings.
- Log malformed rows with line numbers rather than silently dropping them.

### Politeness and Compliance

- Use a configurable request delay between requests (default: 1 second).
- Use bounded concurrency with a configurable maximum (default: 1 concurrent request).
- Respect `robots.txt` and terms of service where applicable.
- Identify with a stable user-agent string (e.g., `Civibus/1.0 (public-records-research; +https://civibus.org)`).
- **Never** bypass authentication, captchas, or anti-bot controls. If encountered, stop and reclassify the source as T4 (out of scope). Civibus does not invest in anti-bot circumvention — no residential proxies, CAPTCHA solving, IP rotation, or trust-accumulation. See `docs/reference/research/acquisition-taxonomy.md`.

---

## Known Failure Modes

Government data portals are notoriously fragile. The scraper must anticipate and handle these common failure patterns:

1. **Session or CSRF tokens** — some portals require a valid session cookie or CSRF token before accepting download requests. The scraper must fetch the initial page, extract any required tokens, and include them in subsequent requests.
2. **Expiring signed URLs** — bulk download links may expire after a short window. The scraper should re-fetch the download page to obtain a fresh URL if a download fails with 403.
3. **Cookie-dependent downloads** — portals that set cookies on the landing page and require them for the actual download. The scraper must maintain a cookie jar across requests.
4. **JS-rendered pagination** — pagination that only works with JavaScript enabled. This is a Playwright-mode case; the scraper should wait for content to load and handle "load more" or infinite-scroll patterns.
5. **Unstable selectors** — CSS selectors or XPath expressions that change between portal updates. Prefer data attributes and semantic selectors over positional or class-based selectors where possible.
6. **Pop-up download flows** — portals that trigger file downloads via JavaScript popups or redirect chains. The Playwright scraper must intercept download events rather than following redirect chains manually.
7. **Intermittent government-portal outages** — portals may go down for maintenance without notice. Retry with backoff; if still down after all retries, report the failure and exit cleanly.
8. **Rate limiting without standard headers** — some portals silently throttle or return truncated data rather than sending 429 responses. Monitor response sizes and content for signs of throttling.

---

## Escalation Rules — When to Stop

Do not guess or work around these situations. Stop and escalate to a human operator:

- **Captcha encountered** — the portal requires solving a captcha to access data.
- **Login required without provided credentials** — `auth_required: true` but no credentials are available.
- **Required human download steps** — the portal requires manual interaction (e.g., accepting a license agreement via a multi-step form) that cannot be automated reliably.
- **Irreducible selector ambiguity** — the page structure is too ambiguous to write reliable selectors, and multiple plausible interpretations would yield different data.
- **Portal changes that break repeatability** — the portal has changed enough that the scraper cannot reliably produce the same output on consecutive runs.
- **Unsupported format** — `format` is `pdf`, `manual`, or any value not in the mode-selection table.

When escalating, report:
- The specific reason for escalation
- What was attempted
- The URL and response state at the point of failure
- Suggested manual steps if obvious

---

## Completion Criteria

The agent may only declare success when ALL of the following are true:

1. The scraper script exists at the correct path and runs without errors against the fixture.
2. The test fixture exists under `scraper/test_data/` with representative data.
3. `scraper/test_scraper.py` passes when run against the fixture (no live network).
4. **Live verification** has been performed against the real URL (see below).
5. No unresolved escalation conditions exist.

### Live Verification

Before declaring success, the agent must run the scraper against the real source URL at least once and report back:

- **URL tested** — the exact URL accessed
- **Run date** — when the live test was performed
- **Files produced** — names and sizes of output files
- **Rows or files retrieved** — count of records or files downloaded
- **Any remaining caveats** — known issues, warnings, or limitations discovered during the live run

If live verification fails, the agent must report the failure and may not declare success.

---

## Example Input/Output Pairs

### Example 1: CSV Direct Download (FEC Bulk Data)

**Input** (`data_sources` entry):

```yaml
name: "FEC Bulk Data - Individual Contributions"
url: "https://www.fec.gov/data/browse-data/?tab=bulk-data"
bulk_download_url: "https://www.fec.gov/files/bulk-downloads/2024/indiv24.zip"
format: "csv"
auth_required: false
update_frequency: "weekly"
coverage:
  start_year: 2024
  transaction_types:
    - contributions
field_mappings:
  CMTE_ID: "committee.fec_committee_id"
  TRANSACTION_AMT: "transaction.amount"
  TRANSACTION_DT: "transaction.transaction_date"
known_issues:
  - "Pipe-delimited, not comma-delimited"
  - "No header row in data file — headers in separate header file"
  - "Dates in MMDDYYYY format"
```

**Expected output artifacts:**

1. `scraper/download.py` — Python script that:
   - Downloads `indiv24.zip` from `bulk_download_url`
   - Extracts the archive
   - Verifies file integrity (expected columns based on known FEC format)
   - Emits scrape metadata (source URL, timestamp, record count, file size)
   - Handles pipe-delimited format per `known_issues`
   - Retries on transient failures with exponential backoff

2. `scraper/test_data/sample_response.csv` — 20–50 representative pipe-delimited records from the FEC bulk format.

3. `scraper/test_scraper.py` — pytest file that:
   - Loads `sample_response.csv` as fixture
   - Verifies column count matches FEC header specification
   - Verifies data types (amount is numeric, date parses)
   - Includes a `@pytest.mark.live` test that hits the real URL (skipped by default)

### Example 2: Web Portal Scraper (NC State Board of Elections)

**Input** (`data_sources` entry):

```yaml
name: "NC State Board of Elections - Campaign Finance"
url: "https://www.ncsbe.gov/campaign-finance"
bulk_download_url: "https://cf.ncsbe.gov/CFOrgLkup/"
format: "web_portal"
auth_required: false
update_frequency: "continuous"
coverage:
  start_year: 2000
  transaction_types:
    - contributions
    - expenditures
    - loans
  office_levels:
    - state_legislature
    - governor
field_mappings:
  source_contributor_name: "entity.name"
  source_amount: "transaction.amount"
  source_date: "transaction.date"
  source_committee: "committee.name"
scraper: "./scraper/scrape.py"
known_issues:
  - "Pre-2008 data has inconsistent employer fields"
  - "Municipal races sometimes missing district info"
```

**Expected output artifacts:**

1. `scraper/scrape.py` — Python Playwright script that:
   - Uses `playwright.sync_api` (Python binding, not TypeScript)
   - Navigates to the portal URL
   - Handles any JS-rendered pagination or search forms
   - Downloads result data (CSV exports if available, or scrapes table rows)
   - Maintains session cookies across requests
   - Uses the existing `scraper` path from config (`./scraper/scrape.py`)
   - Emits scrape metadata (source URL, timestamp, record count)
   - Respects politeness rules (1s delay between page loads)

2. `scraper/test_data/captured_page.html` — captured HTML response from the portal, sufficient to exercise selectors, pagination, and parsing logic.

3. `scraper/test_scraper.py` — pytest file that:
   - Loads `captured_page.html` as fixture
   - Mocks the Playwright browser to serve the fixture
   - Verifies that the scraper extracts expected fields
   - Verifies output shape matches field_mappings expectations
   - Includes a `@pytest.mark.live` test that runs against the real portal (skipped by default)
