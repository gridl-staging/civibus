# Campaign Finance Refresh Runner

This runbook is the canonical operator guide for recurring campaign-finance refreshes.

The federal-first production path is the single scheduled Fly Machine described
below. Non-federal/state refresh runs execute against `civibus-db` from a
controller shell over a lane-owned `flyctl proxy` route; the retired VM material
below is historical reference, not refresh locality.

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
`core/refresh/job_builders.py::build_refresh_plan()`; do not copy a job list
into this runbook.

### Stage 3 Fly Refresh Deployment Evidence

Refresh-app image deploys are owned by
`infra/scripts/deploy_refresh_machine.sh`. Use that script when a registered
stage explicitly authorizes a refresh Machine image update, and keep the
script as the source of truth for build arguments, image proof, and Machine
update behavior.

The 2026-07-31 image shipment is recorded in
`docs/live-state/2026_07_31_refresh_machine_image_deploy.md`. Use that receipt
for historical proof and read-only verification output; do not rerun its
historical `MUTATING — not re-run` commands from Stage 3.

### Automatic scheduler observation

A scheduler watch is read-only and must use the creation-anchored window recorded
in the weekly-refresh row of the frozen roadmap archive (private dev repository;
the row predates the 2026-08-15 Beads cutover and remains valid historical
configuration evidence). Before any Fly or database probe,
record that the watcher issued no lifecycle or production command and prove
there are zero other running Civibus lanes, unless the dispatch record contains
an explicit pre-watch waiver.

Capture timestamped raw output from `flyctl status -a civibus-refresh --json`
and `flyctl machine status 859e0da479e678 -a civibus-refresh` at the start of
the window, after each observed state change, and at the deadline. A passing Fly
observation requires a `start` event inside the window whose source is
scheduler/host-originated rather than user/operator-originated, followed by the
same Machine reaching terminal `stopped` with `exit_code=0`. An absent start at
the deadline is `AUTOMATIC_START_NOT_OBSERVED`; a conflicting event source,
wrong Machine, nonzero exit, or nonterminal state is
`AUTOMATIC_REFRESH_RED`.

After a qualifying Fly start, use the read-only database and active-writer gate
below. Correlate the event window to matching federal `core.refresh_run` rows,
require every executed job to be successful, and reconcile any cadence-skipped
jobs against `core/refresh/job_builders.py::build_refresh_plan()`. Also require
the successful federal/FEC `core.data_source` freshness row used by the public
person probe. The receipt must record the connection host, port, database name,
exact read-only SQL and output, and the row counts used for correlation.

Run the public probes below only after Fly and database correlation pass. Missing,
ambiguous, unavailable, or attribution-conflicted evidence is RED. Record the
first failed condition and stop further downstream probes; only a complete
Fly/DB/public chain is `AUTOMATIC_REFRESH_GREEN`.

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

The dry-run must exit `0` with ten unique ordered keys, with no
`federal-irs-527`. The exact order is tested in
`core/test_refresh_runner.py` and must not be restated here.

For the production DB writer preflight, set `REFRESH_JOB_KEY` to the exact
selected key, start a lane-owned `flyctl proxy` on a lane-owned port, capture
its exact PID for cleanup, and provide credentials through a temporary
mode-`0600` `PGPASSFILE`. Do not put a password in argv. Then run this read-only
probe, substituting the selected proxy port:

```bash
: "${REFRESH_JOB_KEY:?set the exact selected job key}" &&
  printf 'job_key=%s\n' "$REFRESH_JOB_KEY" &&
  : "${CIVIBUS_PROBE_PORT:?set the lane-owned flyctl proxy port}" &&
  PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
  psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$CIVIBUS_PROBE_PORT" \
  -U civibus -d civibus -At -v refresh_job_key="$REFRESH_JOB_KEY" <<'SQL'
SHOW transaction_read_only;
SELECT count(*)
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND datname = current_database()
  AND state LIKE 'idle in transaction%'
  AND xact_start < now() - interval '30 minutes';
SELECT coalesce(max(completed_at)::text, 'never')
FROM core.refresh_run
WHERE job_key = :'refresh_job_key';
SQL
```

The passing output contract is exactly four lines: `job_key=<the selected
key>`, `on`, `0`, and a timestamp-or-`never`. A first line whose key is not
byte-identical to the selected job key, a second line other than `on`, a nonzero
long-idle count, or any failed, empty, or indeterminate read is RED and a hard
stop. The `&&` chain is load-bearing: `${REFRESH_JOB_KEY:?...}` aborts a
non-interactive shell but only prints and continues in the interactive shell an
operator actually pastes into, so the chain is what stops `psql` from running
against an empty key and reporting a fabricated `never`. The
`${CIVIBUS_PROBE_PORT:?...}` link in the same chain is equally load-bearing:
`psql -p ""` does not error, it falls back to the default port 5432, so an
unset proxy port would otherwise probe a workstation Postgres and report a
fabricated PASS from the wrong database. The fourth line is
receipt context, not a gate; read it together with the echoed key, because a
mistyped key also reports `never`. The long-idle count is cross-job by
construction: it is filtered only by `datname` and `pid`, so it counts an
`idle in transaction` backend under any `job_key`, not just the selected one.
Healthy concurrent work under a different `job_key` does not fail this
preflight, but a different-key session holding a transaction idle past 30
minutes does — that is exactly the `state-pa-expenditures` hazard worked
through below, and dismissing a nonzero count because "it is a different lane"
is the mistake this section exists to prevent; same-job in-flight work is not
detected here by design.

`core/refresh/runner.py` is the single same-host same-job serialization owner
through its per-job-key `flock`. No normal refresh job class requires database-wide
quiescence. If a future job class needs global quiescence, this section must
name both its owner and the reason. The writer preflight and the scheduler's
"zero other running Civibus lanes" attribution rule above are distinct: the
latter identifies the source of a scheduler event and must not be removed as a
global writer gate.

> Regional campaign-finance refresh writes have no single fixed execution host.
> The scheduled Machine `859e0da479e678` is pinned to `python -m
> core.refresh.runner --scope federal` and never runs a regional
> `--job-key-prefix` key; regional writes are launched operator-attended via
> `make refresh-cf-data` over a local `flyctl proxy` from a workstation, or from
> an ephemeral `flyctl machine run --rm` machine. The runner's
> `fcntl.flock` guard (`core/refresh/runner.py`, `_RUNNER_LOCK_PATH` and
> `_runner_lock_path_for_job_key`) serializes two runs **only** when they share
> the same host, the same job key, and the same lock-base directory. It provides
> no cross-host serialization, and after a `/var/lock` EACCES fallback to
> `tempfile.gettempdir()/civibus-refresh-runner-<uid>.lock` it does not even
> serialize two same-host runs under different lock bases or different uids. Do
> not rely on the flock to prevent two concurrent same-`job_key` regional runs.

The decision-(b) residual risk is therefore operational: two same-`job_key`
regional runs from different hosts are not serialized and are not
distinguishable in `pg_stat_activity` today. Until cross-host job identity is
implemented, use one named launcher per job key per lane and coordinate that
launcher through the lane receipt. Bead `civibus-ceo` owns the cross-host
`application_name = 'refresh:<job_key>'` identity marker.

**Refresh-run in-flight visibility:** an in-flight `running` `core.refresh_run` row is now representable. The migration
`core/schema/migrations/2026_08_23_refresh_run_running_status.sql` drops the
old terminal-only `completed_at` constraint, adds `running` status, and enforces
the paired running/null-completed invariant. The acceptance proof is recorded in
`docs/live-state/2026_08_23_refresh_in_flight_visibility_acceptance_receipt.md`.

The 30-minute hard stop also detects a concrete transaction-size hazard. The
observed long-lived `idle in transaction` backend 9644 (runner PID 164,
`state-pa-expenditures`) remained open for 13h18m with uncommitted `INSERT`s
into `core.organization`, `core.data_source`, and `core.address`. Those rows
were hidden from every other read-only session and are the likely reason
`civibus-aji.22`'s WA `core.data_source` proof read `0`. This preflight detects
that hazard; Bead `civibus-cqe` owns transaction-size and commit-granularity
remediation.

While a known refresh job is in flight, reuse that same lane-owned `flyctl
proxy`, selected `$CIVIBUS_PROBE_PORT`, and temporary mode-`0600` `PGPASSFILE`
with no password in argv for this second read-only probe:

```bash
PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
  psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$CIVIBUS_PROBE_PORT" \
  -U civibus -d civibus -At <<'SQL'
SELECT application_name,
       state,
       count(*)
FROM pg_stat_activity
WHERE datname = current_database()
  AND application_name LIKE 'refresh:%'
  AND application_name <> 'refresh:runner'
GROUP BY application_name, state
ORDER BY application_name, state;
SQL
```

For a known in-flight job, at least one attributable non-runner row is the
passing condition. The application name is `refresh:<actual_job_key>` when that
value fits PostgreSQL's 63-byte limit. Longer UTF-8 job keys appear as a
truncated `refresh:` prefix plus a stable digest suffix, so match the visible
key prefix and digest-bearing form rather than expecting the full key verbatim.
A `refresh:runner` row by itself is not evidence of job-owned session propagation.
Zero rows when no refresh job is known to be in flight are
non-acceptance rather than failure because the result is inconclusive outside an
in-flight window. Use the isolated local integration proof as the post-land live
proof:

```bash
CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest -m integration core/test_db_application_name_integration.py -q
```

### Federal post-run acceptance probe

This post-run proof is federal-scoped: it belongs to the federal weekly path
above and must not be applied to a `--job-key-prefix` state or local run. After
an authorized federal run reaches terminal non-started state, require both the
content-health owner and the federal person page to report current data. The
person probe uses the expected FEC pull date captured from the read-only
post-run DB receipt and keeps the response body in the pipe:

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

### Non-federal/state job-key-prefix locality

The `--job-key-prefix` non-federal/state execution locality is a controller
shell invoking `core.refresh.runner` against `civibus-db` through a lane-owned
`flyctl proxy "$CIVIBUS_PROBE_PORT":5432 -a civibus-db`. `core/refresh/runner.py`
owns CLI execution, filtering, force, status, and command behavior;
`core/refresh/job_builders.py::build_refresh_plan()` owns the job registry and
selected plan. Do not maintain a documentation job list for state or local
prefixes.

Use the same lane-owned proxy, read-only writer gate, temporary mode-`0600`
`PGPASSFILE`, and no-argv-password discipline defined in "Unattended preflight
and acceptance probes" before any separately authorized non-federal/state run.
Missing writer-gate evidence, an indeterminate proxy route, or a duplicated job
list is red.

Point the runner at that proxy with the DB host/port overrides read by
`core/db.py::_build_connection_parameters`, inheriting the password from the
same `PGPASSFILE` so no password enters argv. Substitute the selected proxy port
and the targeted state or local prefix; `core/refresh/job_builders.py::build_refresh_plan()`
still owns which jobs the prefix selects:

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$CIVIBUS_PROBE_PORT" \
  uv run python -m core.refresh.runner --job-key-prefix state-nc-
```

After an authorized run reaches terminal non-started state, prove the targeted
jurisdiction rather than a federal receipt. Over the same read-only proxy,
require the `core.refresh_run` rows for the run's executed `--job-key-prefix`
jobs to be successful and the matching `core.data_source` freshness row for that
jurisdiction to advance, and reconcile any cadence-skipped jobs against
`core/refresh/job_builders.py::build_refresh_plan()`. Where the targeted
jurisdiction publishes a public surface, verify that jurisdiction's page reports
current data. Do not apply the federal FEC pull-date or federal person-page
proof here; that proof is federal-scoped under "Federal post-run acceptance probe".
The receipt must record the connection host, port, database name, exact
read-only SQL and output, and the row counts used for correlation. Missing,
indeterminate, or unadvanced freshness for the targeted jurisdiction is red.

## Bounded officeholder relink

The production execution and public disposition for the 2026-07-31 relink are
recorded in
`docs/live-state/2026_07_31_production_officeholder_relink.md`. Use that receipt
for measured evidence; do not copy mutable counts into this runbook.

For any separately authorized follow-up, reuse this runbook's existing
lane-owned `flyctl proxy`, writer gate, and read-only probe discipline before
execution. `core/refresh/job_builders.py::build_refresh_plan()` remains the job
registry and plan owner, and `core/refresh/runner.py` remains the dry-run,
filtering, force, status, and command owner. Generate and verify the selected
plan from those owners rather than maintaining a documentation job list.

The predecessor receipt's masters-first diagnostic guidance was superseded by
the later registered batch/L7 scope, wave-order decision, and supervisor ruling.
`federal-fec-masters` is the suspected destructive operation that could
overwrite repaired person links, so it must not run before independent
durability proof. Do not start, stop, restart, or exec Fly Machine
`859e0da479e678`; do not deploy from the relink lane; and do not substitute a
Machine lifecycle action or a duplicated job list for the command owners.

### Recovery and cutover boundary

The third authorized recovery start was consumed on 2026-07-25 and reached
terminal Fly state with process exit `0`, but the Wave 2 receipt is terminal
RED because the public person trust surface still rendered stale source text
instead of `Data is current.` with the DB-derived FEC pull date. The earlier
starts remain part of the ledger: the first ended with `exit_code=1` after a
federal refresh degradation, and the L1R4 start ended with `exit_code=2` before
`core.refresh.runner` started. This lane therefore permits no fourth start,
`77fad` resume, force-stop, second writer or second Machine, production
volume/app identity change, or Debbie deployment. L5 remains blocked because
only a GREEN terminal receipt permits dispatch. Automatic-start acceptance also
remains pending: the 2026-07-28 watch was terminal `AUTOMATIC_REFRESH_RED` at
the no-other-running-Civibus-lane attribution gate, so scheduler-sourced Fly,
DB, and public evidence remained unavailable rather than accepted
(`docs/live-state/2026_07_28_refresh_scheduler_boundary.md`). The next bounded
read-only recheck is `2026-08-04T18:53:21Z` through
`2026-08-04T19:23:21Z`; configuration alone is not acceptance.

## Retired parked VM historical reference

The VM stack is retired, parked, and unreachable for routine refresh support.
Its protected posture is the deny-all-inbound firewall
`civibus-parked-deny-inbound` (`11326537`) recorded in
`docs/howto/operations/hetzner-runbook.md`; do not loosen that firewall or route
non-federal/state refresh work through the VM.

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

- Runner emits one terminal result line per job with key, status, metadata update count,
  and message, plus periodic heartbeat lines while a job is still in flight. A long job such
  as `state-pa-expenditures` therefore reports liveness instead of going silent for hours.
- Heartbeat line shape:
  `<job_key>: heartbeat elapsed_s=<int> refresh_run_id=<uuid> message=Refresh job in flight`.
  The default emission interval is code-owned by `_HEARTBEAT_INTERVAL_SECONDS` in
  `core/refresh/runner.py` and must not be restated as a number here, matching the
  priority-lane ownership rule above.
- Heartbeat lines are operator aid only: they carry no status, never enter the result stream,
  and never affect the exit code. The durable in-flight truth is the `running` row the runner
  commits to `core.refresh_run` before the job executes; read it with the read-only
  `core.refresh_run` correlation described under "Automatic scheduler observation" and the
  read-only probe under "Unattended preflight and acceptance probes".
- Job statuses: `success`, `degraded`, `empty`, `crashed`, `failed`, `skipped`, `dry_run`.
- `run_all_jobs()` isolates failures only when `stop_on_failure=False`; the federal production path (`python -m core.refresh.runner --scope federal`) sets `stop_on_failure=True` and stops on the first failing status.
- Process exits `1` when any result status is `failed`, `crashed`, `degraded`, or `empty`; otherwise exits `0`.
- Metadata writes use `sync_data_source_metadata()` and update `core.data_source.last_pull_at` / `last_pull_status` on matched data sources.
- Process exits `2` without running any job when another runner already holds the global lock, or when neither lock path can be opened. Exit `2` therefore means "nothing ran", not "a job failed"; no `core.refresh_run` receipt is written for it.

### Global runner lock and `--lock-wait-seconds`

`core/refresh/runner.py` takes one exclusive `flock` per distinct job key in the
plan, on paths derived by `_runner_lock_path_for_job_key()` from
`/var/lock/civibus-refresh-runner.lock`, falling back to
`_fallback_runner_lock_path()` (`$TMPDIR/civibus-refresh-runner-<uid>.lock`) where
`/var/lock` is not writable, as on macOS dev hosts. Contention is therefore
per key: a narrowly scoped run competes only with same-host runs whose plan
shares one of its job keys, including a `--scope all` run that covers them.

By default acquisition does not wait: a contended run prints
`Another refresh runner is already active (lock: <path>)`, releases any key locks
it already took, and exits `2`. Pass `--lock-wait-seconds <n>` to queue for the
locks instead of being dropped; the wait budget applies to each key separately.
The value must be finite; `inf`/`nan` are rejected at argument parsing:

```bash
REFRESH_CF_ARGS='--job-key-prefix state-pa-expenditures --pa-year 2026 --force --lock-wait-seconds 1800' \
  make refresh-cf-data
```

Retrying by hand against a busy host is a race; the bounded wait is the supported
way to get a narrow job through. Default `0` keeps the fail-fast behavior for cron
and wrapper callers, which must not stack up behind each other. The key-scoped
lock is not a correctness guarantee — see the serialization caveat above.

### Run bulk loads next to the database

Ingest writes one to two statements per entity through
`core/db_ingest.py::_insert_or_select_existing_id()`, so wall-clock time is
dominated by round-trip latency rather than by row count. Measured through a
laptop `flyctl proxy` on 2026-08-23: **82.89 ms per statement** (200 sequential
round trips in 16.58 s), which projects to roughly **4 hours** for the 57,273-row
PA 2026 expenditures load and matched the observed ~39 KB/s WAL rate. The same
work co-located with the database is sub-millisecond per round trip. Run
acquisition and bulk refresh jobs on the production host per the Hetzner-first
rule in `docs/howto/operations/hetzner-runbook.md`; reserve the proxy path for
probes, gates, and small jobs.

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
