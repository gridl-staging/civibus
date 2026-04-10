# Jurisdiction readme template

Use this file as the human-facing orientation doc for a jurisdiction.
All machine-readable behavior stays in `config.yaml`.

## Acquisition pattern
- Identify whether this jurisdiction uses a bulk file, bulk API, search/export portal, browser-session portal, or a protected/blocked surface.
- Record the dominant acquisition pattern used by the current package, even if multiple source paths exist.

## Preliminary online research
- Capture the official portal family, legal/terms pages, and the first-pass understanding of what source surfaces exist.
- Keep this concise and factual so a future engineer can re-orient quickly.

## Interactive exploration / contract discovery
- Document the exact operator workflow for sources that require navigation, session handling, or repeated manual verification.
- If no interactive exploration is needed, say why the source is direct enough to skip this stage.

## Jurisdiction overview
- Describe jurisdiction level, parent relationship, and naming.
- Record what this config covers and what legal unit it represents.
- Avoid restating schema details; link to the corresponding `config.yaml` sections.

## Data sources summary
- Summarize each `data_sources` entry at a high level (format, scope, and refresh profile).
- Note known authentication or access caveats that are operationally important.

## Coverage notes
- Explain whether the source covers sub-jurisdictions and how `coverage.covers_sub_jurisdictions` was determined.
- Document known gaps by office/election type if they are not encoded directly in `config.yaml`.

## Known data quality issues
- Record observed quality problems before normalizing data in pipelines.
- Keep this section synchronized with `data_sources[].known_issues` and `data_semantics.md`.

## Last verified date
- Record the verification date for source access and laws research.
- Keep this in sync with `laws.last_verified` and source-specific verification dates in `config.yaml`.

## Current lifecycle status
- Summarize where the jurisdiction stands across discovery, source contract, legal semantics, implementation, operations, public claim, and completeness intelligence.
- Keep this aligned with the broader campaign-finance region lifecycle model.

## Evidence artifacts
- Link to the main research, export-contract, screenshot, sample-file, or proof artifacts that back up the current package claims.
- Favor the smallest set of high-signal references needed to re-verify the package.

## Update instructions
- Document the manual steps required to refresh this jurisdiction.
- Include who owns the next refresh and expected monitoring frequency.
- If the portal/API behavior changes, note the minimum reproducible steps to re-run preliminary online research and interactive exploration.
