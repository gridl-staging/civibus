# Prompt: Find Campaign Finance Data Sources

**Agent task:** Research a jurisdiction and produce the source-discovery artifacts for its `config.yaml`.

---

## Input

```
JURISDICTION: {name}
TYPE: {federal | state | county | municipality}
PARENT: {parent jurisdiction, if applicable}
FIPS: {fips code}
```

---

## Instructions

1. Start with **preliminary online research**. Find the official campaign finance disclosure portal for this jurisdiction. Search for "[jurisdiction] campaign finance disclosure data download" and variations.

2. Record the likely acquisition pattern:
   - bulk file
   - bulk API
   - search/export portal
   - browser-session portal
   - protected or blocked
   - unknown

3. Identify the official landing pages, any likely legal/terms pages, and any clues about whether the source covers sub-jurisdictions.

4. Determine what's available:
   - Bulk download (CSV, pipe-delimited, XML, Parquet)? Document the exact URL and any parameters.
   - API? Document the base URL, auth requirements, rate limits, and key endpoints.
   - Web portal with CSV export? Document how to export and what filters are needed.
   - No digital data? Note this and stop.

5. **Critical:** Does this portal cover sub-jurisdictions (county, municipal races) or only its own level? Document explicitly.

6. Download or preview a sample. Document:
   - Column names and data types
   - Encoding (UTF-8? Latin-1?)
   - Date format
   - Any obvious data quality issues

7. If the source requires interactive use, produce **interactive exploration / contract discovery notes**:
   - exact entry URL
   - exact form steps and filters
   - session/cookie requirements
   - export trigger behavior
   - blockers or challenge pages

8. Note any auth requirements, rate limits, or terms of service restrictions on bulk use.

---

## Output

Produce:

1. A short **Preliminary Online Research** summary:
   - official URLs
   - likely acquisition pattern
   - likely cadence clues
   - likely local-vs-state coverage clue
   - legal/terms pages found

2. **Interactive Exploration / Contract Discovery** notes:
   - if no interactive exploration is needed, say why
   - if it is needed, write operator-style steps specific enough that a future scraper implementer can follow them

3. A YAML block ready to paste into `config.yaml`:

```yaml
data_sources:
  - name: ""
    url: ""
    bulk_download_url: null
    api_base_url: null
    format: ""                  # csv | api | web_portal | pdf | pipe_delimited
    auth_required: false
    update_frequency: ""        # continuous | daily | weekly | monthly | quarterly | annual
    coverage:
      start_year: null
      covers_sub_jurisdictions: false   # true if this portal includes county/municipal races
      office_levels: []
      transaction_types: []
    field_mappings:
      # raw column name -> canonical Civibus field path, e.g.:
      # CONTDATE: "transaction.date"
    scraper: null
    last_successful_pull: null
    last_verified_working: null
    known_issues: []
```

4. A brief `README.md` summary (3–5 sentences) covering:
   - what is available
   - how to get it
   - what acquisition pattern it uses
   - the biggest gotchas

---

## Hallucination rules

- Do not invent URLs. If you cannot find a real download URL, say so.
- If the portal exists but you cannot confirm bulk download, say "unconfirmed — requires manual verification."
- Accuracy over completeness. A partial output with honest gaps is better than a fabricated complete one.
