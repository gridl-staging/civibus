# Official Roster Registry Extension Contract

## Purpose and Scope

This file is the canonical extension contract for `body_key`-driven parser and resolver dispatch in `domains/civics/loaders/official_rosters/`.

Scope is limited to official roster dispatch seams:
- `core.data_source.notes.body_key` registration metadata
- parser dispatch (`parse_roster_rows(...)`)
- target resolution dispatch (`_resolve_target(...)`)

Out of scope for this contract:
- schema changes
- source onboarding policy outside roster registry wiring
- new shared constants modules

## Canonical Ownership Chain

Extensions must reuse this exact chain:

1. Register `body_key` in `core.data_source.notes` via [scripts/register_roster_pilot_sources.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/scripts/register_roster_pilot_sources.py:18).
2. Loader selects source + `body_key` from `core.data_source.notes` in [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:95).
3. Parser dispatch occurs through `PARSER_REGISTRY` and `parse_roster_rows(...)` in [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:123).
4. Target resolver dispatch occurs through `TARGET_RESOLVER_REGISTRY` and `_resolve_target(...)` in [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:296).

Do not add alternate routing config, parallel registries, or side-channel body routing.

## Parser Contract (`parsers.py`)

### Row model

`NormalizedRosterRow` fields (all current parsers must emit):
- `member_name`: canonical display name from roster card/link text
- `role_label`: human-readable role title derived by parser
- `district_number`: district identifier string when applicable, else `None`
- `bio_url`: normalized source bio/profile URL or `None`
- `portrait_url`: normalized source portrait URL or `None`

Source: [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:15).

### Parser function signature

Parser implementations in `PARSER_REGISTRY` must match:

```python
(*, source_url: str, html: str) -> list[NormalizedRosterRow]
```

Source: [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:39), [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:74), [test_parser_registry.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_parser_registry.py:30).

### Unknown `body_key` behavior

`parse_roster_rows(...)` raises:

- `ValueError("Unsupported body_key for official roster parsing: {body_key}")`

Source: [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:129), [test_dispatch_characterization.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_dispatch_characterization.py:106).

## Resolver Contract (`loader.py`)

### Resolver function signature

Resolver implementations in `TARGET_RESOLVER_REGISTRY` must match:

```python
(row: NormalizedRosterRow, source_record_id: UUID) -> _ResolvedTarget | None
```

Source: [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:293), [test_loader_registry.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_loader_registry.py:94).

### `_ResolvedTarget` XOR invariant

`_ResolvedTarget` enforces exactly one of:
- `office` (object path), or
- `office_id` (pre-seeded deterministic UUID path)

Setting both or neither raises `ValueError("Exactly one of office or office_id must be set")`.

Source: [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:66), [test_loader_registry.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_loader_registry.py:105).

### Unknown `body_key` behavior

`_resolve_target(...)` raises:

- `ValueError("Unsupported body_key target mapping: {body_key}")`

Source: [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:302), [test_dispatch_characterization.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_dispatch_characterization.py:241).

## Extension Steps (New Roster Source)

1. Add source template + `body_key` in [scripts/register_roster_pilot_sources.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/scripts/register_roster_pilot_sources.py:45), including `notes_payload` fields (`roster_source`, `registry_source_id`, `body_key`).
2. Add parser function in [parsers.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/parsers.py:39) and register it in `PARSER_REGISTRY`.
3. Add resolver function in [loader.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:243) and register it in `TARGET_RESOLVER_REGISTRY`.
4. Keep [harvest_official_roster(...)](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/loader.py:380) as the sole ingest entrypoint; it is the only owner that binds source selection, parser dispatch, resolver dispatch, and upsert flow.
5. If a resolver returns `office_id`, import and reuse the canonical deterministic UUID owner from an importable Python owner module. Do not define UUID literals inline in the resolver and do not create a new shared constants file.

Current owner truth: no current official-roster Python module exports deterministic office UUID constants for resolver imports. Current TARGET_RESOLVER_REGISTRY resolvers return office object targets (office_id=None). If a future roster source needs office_id dispatch, first add deterministic UUID exports to the source's existing canonical owner module, then document that module path here and add registry guard-test coverage.

## Test Ownership Boundaries

- Dispatch characterization contract: [test_dispatch_characterization.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_dispatch_characterization.py:1)
- Parser registry seam contract: [test_parser_registry.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_parser_registry.py:1)
- Loader resolver seam contract: [test_loader_registry.py](/Users/stuart/parallel_development/civibus_dev/apr29_pm_pre_b_dwo_roster_registry_refactor/civibus_dev/domains/civics/loaders/official_rosters/test_loader_registry.py:1)

## Focused Verification Checklist

Run only targeted seam checks for this stage:

```bash
pytest domains/civics/loaders/official_rosters/test_dispatch_characterization.py domains/civics/loaders/official_rosters/test_parser_registry.py domains/civics/loaders/official_rosters/test_loader_registry.py
ruff check domains/civics/loaders/official_rosters/parsers.py domains/civics/loaders/official_rosters/loader.py
```
