---
created: 2026-04-30
updated: 2026-04-30
scope: NC_roster_maintenance_closeout_2026_04_30
---

# NC roster maintenance closeout (replayed dispatch `2026-04-30T09:43:15Z`)

## Dispatch baseline
- Host: `<redacted; VM host in .secret/.env.secret HETZNER_HOST>`
- Repo path: `<redacted VM repo path>`
- Dispatch UTC: `2026-04-30T09:43:15Z`
- Canonical log: `/var/log/civibus/roster_dispatch_20260430_094315.log`
- Pre-dispatch preload command: `uv run python -m scripts.register_roster_pilot_sources`
- Runner command: `uv run python -m core.refresh.runner --scope all --job-key-prefix civics-roster- --force`

## Method
- Parsed per-source status and harvest counters from `/var/log/civibus/roster_dispatch_20260430_094315.log`.
- Pulled production loaded counts by `core.data_source.notes.registry_source_id` from Hetzner PostgreSQL (`127.0.0.1:5433`) after sourcing VM `.env`.
- Compared expected counts from the canonical D/W/O manifest owner (`docs/research/artifacts/2026_04_29_dwo_county_muni/canonical_seat_manifest.json`, mirrored by `domains/civics/loaders/official_rosters/loader.py::manifest_member_counts_by_source_id`).

## Outcome matrix (27 dispatched roster jobs)
| source_id | body_key | job_status | harvest_members | resolved | unresolved | manifest_expected | production_loaded | comparison | recommended_state | failure_mode_or_note |
|---|---|---:|---:|---:|---:|---:|---:|---|---|---|
| nc_apex_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_carrboro_town_council_roster | nc_municipal_council | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_cary_town_council_roster | nc_municipal_council | crashed | n/a | n/a | n/a | 7 | 0 | mismatch | prototyped | Unable to fetch roster HTML for source_id=nc_cary_town_council_roster url=https://www.carync.gov/mayor-council/town-council |
| nc_chapel_hill_town_council_roster | nc_municipal_council | crashed | n/a | n/a | n/a | 9 | 0 | mismatch | prototyped | Unable to fetch roster HTML for source_id=nc_chapel_hill_town_council_roster url=https://www.chapelhillnc.gov/government/mayor-and-council |
| nc_chccs_school_board_roster | nc_school_board | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_dps_school_board_roster | nc_school_board | success | 0 | 0 | 0 | 7 | 0 | mismatch | prototyped | harvest succeeded but manifest-vs-loaded counts diverge; keep prototyped until parser/load contract is closed |
| nc_durham_city_council_roster | durham_city_council | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_durham_county_commissioners_roster | nc_county_commissioners | success | 5 | 5 | 0 | 5 | 5 | match | validated | live run succeeded with full resolve/load match |
| nc_fuquay_varina_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_garner_town_council_roster | nc_municipal_council | crashed | n/a | n/a | n/a | 6 | 0 | mismatch | prototyped | Unable to fetch roster HTML for source_id=nc_garner_town_council_roster url=https://www.garnernc.gov/government/town-council/town-council-members |
| nc_general_assembly_house_roster | nc_house | success | 124 | 124 | 0 | n/a | 124 | n/a (not in canonical manifest) | validated | live run succeeded with full resolve/load match |
| nc_hillsborough_town_council_roster | nc_municipal_council | crashed | n/a | n/a | n/a | 6 | 0 | mismatch | prototyped | Unable to fetch roster HTML for source_id=nc_hillsborough_town_council_roster url=https://www.hillsboroughnc.gov/about-us/mayor-and-board/ |
| nc_holly_springs_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_knightdale_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_morrisville_town_council_roster | nc_municipal_council | crashed | n/a | n/a | n/a | 7 | 0 | mismatch | prototyped | Unable to fetch roster HTML for source_id=nc_morrisville_town_council_roster url=https://www.morrisvillenc.gov/government/meet-your-town-council |
| nc_ocs_school_board_roster | nc_school_board | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_orange_county_commissioners_roster | nc_county_commissioners | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_raleigh_city_council_roster | nc_municipal_council | success | 8 | 8 | 0 | 8 | 8 | match | validated | live run succeeded with full resolve/load match |
| nc_registers_of_deeds_roster | nc_registers_of_deeds | success | 100 | 0 | 100 | 100 | 0 | mismatch | prototyped | harvest succeeded but manifest-vs-loaded counts diverge; keep prototyped until parser/load contract is closed |
| nc_rolesville_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_sheriffs_association_roster | nc_sheriffs | success | 100 | 100 | 0 | 100 | 100 | match | validated | live run succeeded with full resolve/load match |
| nc_soil_water_supervisors_roster | nc_soil_water_supervisors | success | 0 | 0 | 0 | 492 | 0 | mismatch | prototyped | harvest succeeded but manifest-vs-loaded counts diverge; keep prototyped until parser/load contract is closed |
| nc_wake_county_commissioners_roster | nc_county_commissioners | success | 7 | 7 | 0 | 7 | 7 | match | validated | live run succeeded with full resolve/load match |
| nc_wake_forest_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_wcpss_school_board_roster | nc_school_board | success | 9 | 9 | 0 | 9 | 9 | match | validated | live run succeeded with full resolve/load match |
| nc_wendell_town_council_roster | nc_municipal_council | success | 6 | 6 | 0 | 6 | 6 | match | validated | live run succeeded with full resolve/load match |
| nc_zebulon_town_council_roster | nc_municipal_council | success | 0 | 0 | 0 | 6 | 0 | mismatch | prototyped | harvest succeeded but manifest-vs-loaded counts diverge; keep prototyped until parser/load contract is closed |

## Failure/blocked-source artifacts
- Failed jobs in this dispatch: `nc_cary_town_council_roster`, `nc_garner_town_council_roster`, `nc_morrisville_town_council_roster`, `nc_chapel_hill_town_council_roster`, `nc_hillsborough_town_council_roster`.
- Durable failure evidence for each failed source is captured in the canonical replay log path above and in this matrix row set (message begins `Unable to fetch roster HTML ...`).
- This closeout does not classify any source as `deferred`; all failures remain `prototyped` pending parser/HTTP contract closure evidence.

## State-transition decision summary
- Promote to `validated`: 18 roster sources with successful runs and manifest/loaded count agreement.
- Keep `prototyped`: 8 roster sources with crash outcomes or count divergence (`registers`, `soil_water`, `dps`, `zebulon` and the 5 crashed municipal sources).
- Keep `validated` for `nc_general_assembly_house_roster` with this dispatch as refreshed replay evidence (source is outside the D/W/O manifest but in dispatch scope).

