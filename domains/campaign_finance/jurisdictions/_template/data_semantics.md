# Jurisdiction data semantics template

This document captures field-by-field assumptions used during parsing and normalization.
Keep it tightly synchronized with `data_sources[].field_mappings` and `config.yaml`.

## Acquisition contract summary
- Record the concrete access surface used by the package: file/API/export names, response format, delimiter, and any parameters that materially affect retrieval.
- This is the compact source-contract summary that sits between discovery notes and implementation code.

## Date fields
- List canonical date formats encountered in source files and the normalization output format.
- Note timezone assumptions, null handling, and timezone conversions for partial timestamps.

## Name formats
- Record canonical parsing rules for person and committee names.
- Call out suffixes, committee suffix inconsistencies, and common abbreviation normalization rules.

## Employer/occupation
- Document free-text field behavior, expected null strings, and normalization dictionary hints.
- Note any common occupation aliases that affect entity resolution or filtering.

## Address format
- Capture address parsing expectations, country/state abbreviation assumptions, and parser fallbacks.
- Record geocoder-sensitive cleanup rules and how missing components are represented.

## Committee IDs
- Record formats of committee identifiers and any jurisdiction-specific normalization needed.
- Note duplicate identifier patterns and when fallback composite IDs are required.

## Amendment handling
- Document how amended filings are represented in raw source and how duplicates/corrections should be resolved.
- State whether overwrite, upsert, or append semantics are used by each source.

## Missing/null conventions
- Define how blanks, placeholders, and sentinel values are normalized.
- Record where this template requires explicit `null` even for optional fields.

## Interactive Exploration / Contract Discovery
- Document exact navigation or live verification steps required to retrieve data (entry URL, form interactions, filters, download/export trigger).
- For direct bulk or API sources, use this section to explain the exact live verification steps instead of leaving it blank.
- Include selector hints only where stable enough to be implemented.
- Every quirk captured here is a required normalization test case in `test_normalize.py`.
