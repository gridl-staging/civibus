# Civibus

Universal public-records intelligence platform. Civibus links campaign finance, property, corporate, environmental, court, and legislative records into a single provenance-first knowledge graph.

Campaign finance is the active launch domain.

## Current Status

Status, scope, and coverage are maintained in `PROJECT_OVERVIEW.md` and `ROADMAP.md`,
not duplicated here. As of 2026-06-03 the project is on a **federal-first v1**
scope — a bounded directory of 543 elected federal officials (Congress +
delegates + President/VP) with FEC money and Schedule E independent expenditures.
The prior multi-state stack is parked, and its Hetzner prod deployment is
currently down (verified 2026-06-03). See `PROJECT_OVERVIEW.md` and
`decisions/2026-06-03_federal_first_v1_a_congress_directory_fec_money_as_the_launch_slice.md`.

`ROADMAP.md` is the project SSOT for open work, current gates, and priority
ordering. Fresh-laptop setup:
`docs/howto/operations/dev_environment_setup.md`.

## Running

```bash
make db-up
make db-reset
make ingest-fec-bulk-sample
make ingest-ca-sample
make ingest-ga-sample
make ingest-il-sample
make refresh-cf-data REFRESH_CF_ARGS=""
make lint
make validate-configs
make validate-registry
```

Maintenance note: retired symbols are declared inline in `Makefile` (`RETIRED_SYMBOLS` and `RETIRED_ALLOWLIST`), and `make lint` enforces them repo-wide via `check-retired-symbols`. Add future retirements to that single list/allowlist instead of creating a second registry.

Default local DB:

- host: `localhost`
- port: `5433`
- user: `civibus`
- database: `civibus`
- password: `civibus_dev`

Prefer focused pytest runs during routine work. Repo guidance says to ask before running the full `make test` suite.

## Read Next

1. [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md)
2. [`ROADMAP.md`](ROADMAP.md)
3. [`AGENTS.md`](AGENTS.md)
4. [`docs/reference/research/coverage-registry.json`](docs/reference/research/coverage-registry.json)
5. [`docs/reference/research/coverage-audit-contract.md`](docs/reference/research/coverage-audit-contract.md)
