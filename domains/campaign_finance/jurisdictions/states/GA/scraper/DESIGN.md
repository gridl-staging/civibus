# GA Scraper Stage 1 Design

This document locks the GA scraper module boundaries and source-key strategy before parser/loader implementation.

## Module Layout

- `__init__.py`
  - Loads GA `data_sources` blocks from `config.yaml`.
  - Exposes `CONTRIBUTION_COLUMNS` and `EXPENDITURE_COLUMNS` from ordered `field_mappings` keys.
  - Single source of truth for GA source metadata and column order: `config.yaml`.
- `parse.py`
  - Parse contribution CSV rows and expenditure HTML-table rows.
  - Own shared row parsing helpers: `parse_ga_date`, `parse_ga_amount`, and `infer_entity_type`.
- `extract.py`
  - Convert parsed row dicts into Pydantic entity models.
  - Provide config-backed `build_data_source()` helper for GA data source records.
- `load.py`
  - Insert into database via `core/db.py` and `core/db_ingest.py` primitives.
  - Return a single `LoadResult` shape with shared provenance handling.
- `cli.py`
  - Parse arguments, support dry-run behavior, manage DB lifecycle, dispatch ingest path.
- `download.py`
  - Implements optional Stage 7 portal automation with Playwright sync API.
  - Uses config-backed URL resolution (`build_search_url`) via `__init__.py` helpers.
  - Encapsulates search form-fill and export trigger steps for a single ASP.NET session/browser context.
  - Raises a call-time runtime error when Playwright is not installed so non-download GA modules remain importable.

## Dependencies

Observed fixture payloads:
- `contribution_export_sample.xls` is CSV text.
- `expenditure_export_sample.xls` is an HTML table payload.
- Both header rows match ordered `field_mappings` keys in `config.yaml`.

Decision:
- `beautifulsoup4` is **not required** for core Stage 3 parsing based on observed simple table markup.
- Python standard-library `html.parser` is sufficient for Stage 3 scope.
- `lxml` backend is not justified by current fixture complexity.
- `playwright` is only needed for optional Stage 7 portal automation and should not be a Stage 1/3 runtime dependency.

`pyproject.toml` dependency strategy:
- Keep `playwright` isolated under `[project.optional-dependencies].download`.
- Core runtime and default test commands do not require Playwright.
- Portal automation users opt in with `uv sync --extra download` and install browser binaries separately.

Import-guard pattern:
- `download.py` catches Playwright import errors at module import time.
- `download_ga_export(...)` enforces the dependency at call time via a descriptive `RuntimeError`.
- This keeps `parse.py`, `extract.py`, `load.py`, and core GA CLI imports usable without the download extra.

Approval gate:
- Any new dependency remains maintainer approval-gated before editing `pyproject.toml`.

## Source-Record Keys

Contributions:
- GA contribution exports have no stable per-row source identifier.
- Use `record_hash` (SHA-256 of `raw_fields`) for deduplication.
- Set `source_record_key` to the same `record_hash` value because
  `try_insert_source_record(...)` deduplicates only non-null keys.

Expenditures:
- Use the same `record_hash`-as-`source_record_key` strategy as contributions.
- Rationale: fixture rows show `Key`/`Ref` collisions, so these fields are not sufficiently stable as a unique source key.

## Amendment Handling

- GA exports do not expose amendment/supersession flags on contribution or expenditure rows.
- Ingest semantics are append-only at export-row level.
- Supersession resolution is out of scope until report-log joins are added.

## Entity Classification

Entity inference rule:
- `FirstName` empty and `LastName` populated -> classify as organization.
- `FirstName` and `LastName` populated -> classify as person.

Placement decision:
- `infer_entity_type` lives in `parse.py` as row-level classification logic.
- `extract.py` reuses that function; no duplicate classifier logic.

Known refinement gap:
- PAC/trust edge cases are tracked as future refinement beyond Stage 1.
