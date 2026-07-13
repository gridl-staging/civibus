---
created: 2026-04-29
updated: 2026-04-29
---

# Stage 1 Preflight Contract (D/W/O County + Municipal Rosters)

## Purpose

Freeze Stage 1 prerequisites and canonical-owner boundaries before any new D/W/O `body_key`, source row, refresh job, or L14 expected-count wiring is added.

## Prerequisite ancestry checks (hard gate)

Commands run on branch `batman/apr29_pm_4_dwo_county_municipal_rosters` at `HEAD=f5a0ce21`:

```bash
git merge-base --is-ancestor batman/apr29_pm_pre_a_dwo_schema_migrations HEAD
git merge-base --is-ancestor batman/apr29_pm_pre_b_dwo_roster_registry_refactor HEAD
```

Observed results:

- `pre_a_exit=1`
- `pre_b_exit=1`

Supporting evidence:

- Merge-base between `HEAD` and both prerequisite branches is `0899d524`.
- Pre-branch heads are ahead of that base (`batman/apr29_pm_pre_a_dwo_schema_migrations=239cd0c5`, `batman/apr29_pm_pre_b_dwo_roster_registry_refactor=4b78aa9d`).
- `main` currently points to `6bb9c50e` (merge commit titled `merge: integrate apr29 pre-b roster registry refactor`) and is not an ancestor of current `HEAD`.

Conclusion: Stage 1 hard preflight fails on this branch as currently checked out. Per checklist, Stage 1 execution must halt and branch ancestry must be rebased onto `main` before downstream implementation stages proceed.

## Canonical owner audit (approved extension seams)

The current branch still shows the expected owner seams; later stages must extend these seams only:

1. Official roster ingestion owner:
- `domains/civics/loaders/official_rosters/parsers.py:155-163` (`parse_roster_rows` body-key dispatch)
- `domains/civics/loaders/official_rosters/loader.py:87-124` (`_select_roster_source_definition` from `core.data_source` + `notes`)
- `domains/civics/loaders/official_rosters/loader.py:127-139` (`_fixture_or_live_html`)
- `domains/civics/loaders/official_rosters/loader.py:235-300` (`_resolve_target`)
- `domains/civics/loaders/official_rosters/loader.py:378-470` (`harvest_official_roster`)
- `domains/civics/loaders/official_rosters/cli.py:27-72` (`main`)

2. Registry + refresh + L14 owners:
- `sources.yaml:49-90` (existing official-roster source rows)
- `core/refresh/job_builders.py:934-973` (`build_refresh_plan`)
- `core/keel_gate_l14.py:106-150` (`collect_coverage_matrix`)
- `core/keel_gate_l14.py:157-190` (`write_l14_evidence`)
- `core/keel_gate_l14.py:203-237` (`main`)

3. Regression surfaces reviewed for future stages:
- `domains/civics/loaders/official_rosters/test_parsers.py`
- `domains/civics/loaders/official_rosters/test_loader.py`
- `domains/civics/loaders/official_rosters/test_cli.py`

4. Legacy pilot script inspected for reference-only context:
- `scripts/register_roster_pilot_sources.py:19-70` (`RosterSourceTemplate` list)
- `scripts/register_roster_pilot_sources.py:120-128` (`register_roster_pilot_sources`)

Contract statement: new D/W/O source truth must live in `sources.yaml` + `core.data_source` metadata (`notes.registry_source_id`, `notes.body_key`), not in expanded script-local template lists.

## Open questions

- None for owner boundaries.
- Branch ancestry remains unresolved until rebase is performed.
