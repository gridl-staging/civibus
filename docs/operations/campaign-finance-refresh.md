# Campaign Finance Refresh Runner

This runbook is the canonical operator guide for recurring campaign-finance refreshes.

Status boundary (2026-03-25): the repo-controlled installer and wrappers below are
shipped and tested. Production first-boot prerequisites are now owned by
`infra/scripts/bootstrap_prod_vm.sh`; cron installation still depends on a successful
VM bootstrap plus a populated production `.env`.

## Bootstrap production VM

The production bootstrap path is:

```bash
bash infra/scripts/bootstrap_prod_vm.sh
```

The script is designed for root execution on the target VM and is the single source of
truth for first-boot prerequisites: Docker, Compose, checkout path, and `.env`
materialization. The deploy workflow calls it before the remote compose rollout.

## Production checkout path

All cron and wrapper commands in this runbook assume the production checkout path:
`/root/civibus/civibus_dev`.

## Install managed cron entries

```bash
cd /root/civibus/civibus_dev
bash infra/scripts/install_refresh_cron.sh
```

The installer is the single source of truth for schedule text and installs:

```cron
0 */6 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_priority.sh >> /var/log/civibus/refresh-priority.log 2>&1
20 */6 * * * bash /root/civibus/civibus_dev/infra/scripts/run_keel_gates.sh >> /var/log/civibus/keel-gates.log 2>&1
0 3 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_fec_bulk.sh >> /var/log/civibus/refresh-fec-bulk.log 2>&1
0 17 * * 0 bash /root/civibus/civibus_dev/infra/scripts/refresh_nc_orchestrator.sh >> /var/log/civibus/refresh-nc-orchestrator.log 2>&1
30 2 * * * bash /root/civibus/civibus_dev/infra/scripts/backup_to_b2.sh >> /var/log/civibus/backup.log 2>&1
0 6 * * * bash /root/civibus/civibus_dev/infra/scripts/check_cert_expiry.sh >> /var/log/civibus/check-cert.log 2>&1
```

## Wrapper runtime contract

All wrappers (`infra/scripts/refresh_priority.sh`,
`infra/scripts/refresh_fec_bulk.sh`, `infra/scripts/run_keel_gates.sh`,
`infra/scripts/refresh_nc_orchestrator.sh`)
enforce the same baseline contract:

- load literal `KEY=VALUE` assignments from `.env` without executing shell code
- `PATH="$HOME/.local/bin:$PATH"` for cron-safe `uv` discovery
- required `POSTGRES_PASSWORD`
- host-to-Docker DB overrides:
  - `POSTGRES_HOST=127.0.0.1`
  - `POSTGRES_PORT=5432`

Priority wrapper specifics (`infra/scripts/refresh_priority.sh`):

- optional `NC_COMMITTEE_DOCS_PATH`; if set, the wrapper resolves relative paths
  against repo root and exits on missing file
- execution entrypoint: `make refresh-cf-priority`

FEC bulk wrapper specifics (`infra/scripts/refresh_fec_bulk.sh`):

- required `FEC_BULK_CYCLE`
- default bulk directory:
  `FEC_BULK_DIR=${FEC_BULK_DIR:-/var/lib/civibus/fec/bulk/${FEC_BULK_CYCLE}}`
- operator override is allowed via `FEC_BULK_DIR` (for example
  `/var/civibus/fec-bulk/${FEC_BULK_CYCLE}`), but `/var/lib/civibus/fec/bulk/...`
  is the committed default
- execution entrypoints:
  - `make download-fec-bulk`
  - `make ingest-fec-bulk`

Keel gates wrapper specifics (`infra/scripts/run_keel_gates.sh`):

- execution entrypoints:
  - `make gate-L5`
  - `make gate-L7`

NC orchestrator wrapper specifics (`infra/scripts/refresh_nc_orchestrator.sh`):

- execution entrypoint delegates to the existing NC CLI orchestrator:
  `uv run --extra download python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli --data-type transactions --orchestrate-committees --window-start "${WINDOW_START}" --window-end "${WINDOW_END}"`
- wrapper derives its rolling UTC date window internally:
  - `WINDOW_START="$(date -u '+%Y-01-01')"`
  - `WINDOW_END="$(date -u '+%Y-%m-%d')"`

## Priority-lane ownership

Priority membership is code-owned by
`core/refresh/runner.py::_priority_source_names()` and must not be duplicated as a
hard-coded list in docs. This keeps docs synchronized with runtime selection logic.

## Failure reporting and exit behavior

- Runner emits one line per job with key, status, metadata update count, and message.
- Job statuses: `success`, `failed`, `skipped`, `dry_run`.
- `run_all_jobs()` isolates failures; one failing job does not prevent later jobs from running.
- Process exits `1` if any job fails; otherwise exits `0`.
- Metadata writes use `sync_data_source_metadata()` and update `core.data_source.last_pull_at` / `last_pull_status` on matched data sources.

## Manual wrapper execution

Use wrapper scripts for manual execution so runtime behavior matches cron behavior:

```bash
bash infra/scripts/refresh_priority.sh
bash infra/scripts/refresh_fec_bulk.sh
bash infra/scripts/run_keel_gates.sh
bash infra/scripts/refresh_nc_orchestrator.sh
```

For ad-hoc priority runs that include NC transaction jobs:

```bash
NC_COMMITTEE_DOCS_PATH=/root/civibus/data/nc/committee-docs.csv \
bash infra/scripts/refresh_priority.sh
```
