# Civibus

Universal public-records intelligence platform. Civibus links campaign finance, property, corporate, environmental, court, and legislative records into a single provenance-first knowledge graph.

Campaign finance is the active launch domain. The current work is proving live government-data acquisition, keeping coverage status truthful, and expanding runner-wired state support.

## Current Status

Real government campaign-finance data is now served from the production VM, and the main bottleneck is coverage validation, not frontend polish.

- Refresh runner surface: FEC + 13 states (`CA`, `CO`, `FL`, `GA`, `IL`, `IN`, `MN`, `NC`, `NJ`, `PA`, `TX`, `WA`, `WI`)
- Illinois now has bounded live proof against the official portal, including live DB-backed ingest on isolated Postgres
- Illinois is still not launch-ready because the portal's repeat publication cadence remains unverified

`ROADMAP.md` is the project SSOT for open work. `PRIORITIES.md` explains what matters now and what not to work on.

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

Default local DB:

- host: `localhost`
- port: `5433`
- user: `civibus`
- database: `civibus`
- password: `civibus_dev`

Prefer focused pytest runs during routine work. Repo guidance says to ask before running the full `make test` suite.

## Read Next

1. [`ROADMAP.md`](/Users/stuart/repos/gridl-dev/civibus_dev/ROADMAP.md)
2. [`PRIORITIES.md`](/Users/stuart/repos/gridl-dev/civibus_dev/PRIORITIES.md)
3. [`AGENTS.md`](/Users/stuart/repos/gridl-dev/civibus_dev/AGENTS.md)
4. [`docs/research/coverage-registry.json`](/Users/stuart/repos/gridl-dev/civibus_dev/docs/research/coverage-registry.json)
5. [`docs/research/coverage-audit-contract.md`](/Users/stuart/repos/gridl-dev/civibus_dev/docs/research/coverage-audit-contract.md)
