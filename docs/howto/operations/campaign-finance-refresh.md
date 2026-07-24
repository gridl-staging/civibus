# Campaign Finance Refresh Runner

This runbook is the canonical operator guide for recurring campaign-finance refreshes.

The federal-first production path is the single scheduled Fly Machine described
below. The VM cron and wrapper material remains for legacy and non-federal
priority support; it is not a second federal scheduler.

## Federal-first weekly Fly Machine

App `civibus-refresh` has exactly one scheduled Machine,
`859e0da479e678`. Its immutable runtime contract is:

- command: `python -m core.refresh.runner --scope federal`;
- schedule: `weekly`, anchored to Machine creation at
  `2026-07-07T18:53:21Z`;
- restart policy: `no`;
- scratch volume: `vol_42kzg23gem178304` (`civibus_refresh_data`) mounted at
  `/data`; and
- production database: `civibus-db.internal:5432`, database `civibus`.

The runtime job registry and federal ordering remain code-owned by
`core/refresh/job_builders.py`; do not copy a job list into this runbook.

### Unattended preflight and acceptance probes

These Machine probes are read-only. They must show exactly one Machine and the
expected stopped state/config before any separately authorized execution:

```bash
flyctl machine list -a civibus-refresh
flyctl machine status 859e0da479e678 -a civibus-refresh
flyctl machine status 859e0da479e678 -a civibus-refresh -d
```

Prove the repository plan locally before considering production:

```bash
uv run python -m core.refresh.runner --scope federal --dry-run
```

The dry-run must exit `0` with nine unique ordered keys, with no
`federal-irs-527`. The exact order is tested in
`core/test_refresh_runner.py` and must not be restated here.

For the production DB writer gate, start a lane-owned `flyctl proxy` on a
lane-owned port, capture its exact PID for cleanup, and provide credentials
through a temporary mode-`0600` `PGPASSFILE`. Do not put a password in argv.
Then run this read-only probe, substituting the selected proxy port:

```bash
PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
  psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$CIVIBUS_PROBE_PORT" \
  -U civibus -d civibus -At <<'SQL'
SHOW transaction_read_only;
SELECT count(*)
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND datname = current_database()
  AND state = 'active'
  AND query ~* '\m(insert|update|delete|copy|truncate|merge)\M'
  AND (
    query ~* '\mcf\.'
    OR query ~* 'core\.refresh_run'
    OR query ~* 'core\.data_source'
  );
SQL
```

The only passing output is `on` followed by `0`. A missing, indeterminate, or
nonzero writer count is a hard stop.

After an authorized run reaches terminal non-started state, require both the
content-health owner and the selected target person page to report current
data. The person probe uses the expected FEC pull date captured from the
read-only post-run DB receipt and keeps the response body in the pipe:

```bash
curl -fsS --max-time 40 \
  https://civibus.shareborough.com/api/health/content |
  uv run python -c 'import json,sys; assert json.load(sys.stdin) == {"healthy": True}'

: "${EXPECTED_FEC_PULL_DATE_UTC:?set from the post-run FEC source receipt}"
curl -fsS --max-time 40 \
  https://civibus.shareborough.com/person/d2944415-3ec6-47b0-b44f-2cd28ddfbc0b |
  EXPECTED_FEC_PULL_DATE_UTC="$EXPECTED_FEC_PULL_DATE_UTC" uv run python -c \
  'import os,sys; body=sys.stdin.read(); assert "Source and freshness" in body; assert "Data is current." in body; assert os.environ["EXPECTED_FEC_PULL_DATE_UTC"] in body'
```

The public `/api/health/content` route maps to the API container's
`/health/content` owner. A non-200 response, a body other than
`{"healthy":true}`, a missing current-data label, or a missing expected pull
date is red.

### Recovery and cutover boundary

The Stage 2 one-shot was consumed and ended red (`exit_code=1`,
`federal-fec-masters` degraded). This lane therefore permits no `77fad`
resume, force-stop, second writer or second Machine, production volume/app
identity change, or Debbie deployment. Do not start the Machine again under
this receipt. Automatic-start acceptance also remains pending until the actual
creation-anchored weekly boundary produces observed Fly events; configuration
alone is not acceptance.

## Legacy VM and non-federal priority support

Status boundary (2026-03-25): the repo-controlled installer and wrappers below
are shipped and tested. Production first-boot prerequisites are owned by
`infra/scripts/bootstrap_prod_vm.sh`; cron installation still depends on a
successful VM bootstrap plus a populated production `.env`.

### Bootstrap production VM

The production bootstrap path is:

```bash
bash infra/scripts/bootstrap_prod_vm.sh
```

The script is designed for root execution on the target VM and is the single source of
truth for first-boot prerequisites: Docker, Compose, checkout path, and `.env`
materialization. The deploy workflow calls it before the remote compose rollout.

### Production checkout path

All cron and wrapper commands in this runbook assume the production checkout path:
`/root/civibus/civibus_dev`.

### Install managed cron entries

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

### Wrapper runtime contract

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

### Priority-lane ownership

Priority membership is code-owned by
`core/refresh/runner.py::_priority_source_names()` and must not be duplicated as a
hard-coded list in docs. This keeps docs synchronized with runtime selection logic.

## Failure reporting and exit behavior

- Runner emits one line per job with key, status, metadata update count, and message.
- Job statuses: `success`, `degraded`, `empty`, `crashed`, `failed`, `skipped`, `dry_run`.
- `run_all_jobs()` isolates failures only when `stop_on_failure=False`; the federal production path (`python -m core.refresh.runner --scope federal`) sets `stop_on_failure=True` and stops on the first failing status.
- Process exits `1` when any result status is `failed`, `crashed`, `degraded`, or `empty`; otherwise exits `0`.
- Metadata writes use `sync_data_source_metadata()` and update `core.data_source.last_pull_at` / `last_pull_status` on matched data sources.

### Manual wrapper execution

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
