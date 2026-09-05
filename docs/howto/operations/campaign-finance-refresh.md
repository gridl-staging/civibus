# Campaign Finance Refresh Runner

This runbook is the canonical operator guide for recurring campaign-finance refreshes.

The federal-first production path is the single scheduled Fly Machine described
below. Non-federal/state refresh runs execute against `civibus-db` from a
controller shell over a lane-owned `flyctl proxy` route; the retired VM
[bootstrap and checkout](./campaign_finance_refresh_retired_vm.md) remains historical reference, not refresh locality. A dedicated regional
scheduled-Machine profile is frozen below, but it is not provisioned or
execution-ready and does not yet replace the controller-shell locality.

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

## Production execution-origin migration owner

`core.schema.apply_migrations` retains its zero-argument release behavior and
also owns one pinned production path for
`2026_08_27_refresh_run_execution_origin.sql`. A later authorized database
owner must first establish the existing lane-owned `flyctl proxy` to
`civibus-db:5432`, select `CIVIBUS_PROBE_PORT`, and install the temporary
mode-`0600` `PGPASSFILE` exactly as specified in "Unattended preflight writer
gate" below. Passwords must not appear in argv. Bind the connection environment
to that independently selected route, then use read-only for `preflight`, a
writer for `apply`, and read-only again for `verify`:

```bash
: "${CIVIBUS_PROBE_PORT:?set the already-running lane-owned proxy port}" &&
: "${PGPASSFILE:?set the temporary mode-0600 password file}" &&
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$CIVIBUS_PROBE_PORT" POSTGRES_DB=civibus &&
PGOPTIONS='-c default_transaction_read_only=on' uv run python -m core.schema.apply_migrations \
  --production-execution-origin preflight --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus &&
uv run python -m core.schema.apply_migrations \
  --production-execution-origin apply --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus &&
PGOPTIONS='-c default_transaction_read_only=on' uv run python -m core.schema.apply_migrations \
  --production-execution-origin verify --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus
```

This target pins the artifact digest, requires an exact singleton pending delta
and absent target shape, blocks running refreshes and long-idle transactions,
takes one transaction advisory lock, and atomically applies, records, and
verifies the migration. It also fixes database user `civibus` and server port
`5432`. Identity, read mode, lock, schema, or ledger drift fails closed. The
procedure is not production-write authorization.

The schema preflight accepts both repository-supported catalog encodings of
`NOT NULL`: the pre-18 form, where `pg_attribute.attnotnull` is exact and there
are no `pg_constraint.contype = 'n'` rows, and the PostgreSQL 18 form, where
there is exactly one validated, enforced, local, non-inherited single-column
`n` row for every expected non-null column. A partial, duplicate, extra,
multi-column, unvalidated, unenforced, inherited, or wrong-column set is RED.
Table ownership, columns, nullability, defaults, ordinary checks, primary keys,
and the migration-ledger shape remain exact in either form.

## Production authority-scoped identity migration owner

The same module owns one separate, digest-bound production path for exactly
`domains/campaign_finance/schema/migrations/2026_08_28_authority_scoped_identity.sql`
(current SHA-256
`0f463ecd2877c35c2754867c3994aa135c89e006554baa58697e6ff20d4badc8`).
The former monolithic digest
`310cfcd3106c70039d947bdd20ba1cc001072d8bf96969390ad162edab9416ed` is
safely superseded only because R19 durably proved that its timed-out attempt
left zero target columns and zero rows for the original filename in
`core.schema_migrations`. R19 is terminal RED: it must never be retried, and
the owner must never raise the 60-minute limit. Any other pre-existing shape
or receipt fails closed rather than invoking this supersession contract.
It never scans or applies another domain migration. Before using it, the
authorized database owner must establish the existing lane-owned `flyctl
proxy` route and temporary mode-`0600` `PGPASSFILE` described above. Run this
one chained command against exactly `127.0.0.1:<lane port>/civibus`; do not put
a password in argv or export `POSTGRES_PASSWORD`:

```bash
: "${CIVIBUS_PROBE_PORT:?set the already-running lane-owned proxy port}" &&
: "${PGPASSFILE:?set the temporary mode-0600 password file}" &&
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$CIVIBUS_PROBE_PORT" POSTGRES_DB=civibus &&
PGOPTIONS='-c default_transaction_read_only=on' uv run python -m core.schema.apply_migrations \
  --production-authority-scoped-identity preflight --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus &&
uv run python -m core.schema.apply_migrations \
  --production-authority-scoped-identity apply --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus &&
PGOPTIONS='-c default_transaction_read_only=on' uv run python -m core.schema.apply_migrations \
  --production-authority-scoped-identity verify --expected-host 127.0.0.1 \
  --expected-port "$CIVIBUS_PROBE_PORT" --expected-database civibus
```

`preflight` and `verify` require read-only connections. All three phases pin
the exact migration digest and database user/server identity, require every
core migration already receipted, reject any unrelated pending core migration,
and fail closed while a refresh writer or long-idle transaction exists.
`pending_absent` requires both the ledger row and every target column to be
absent. `partial_resumable` requires all ten target columns, exact protective
triggers, views, not-yet-promoted constraints, and exactly four digest-bound
rows in the transient
`core.authority_scoped_identity_migration_progress` table. Already-present
state is accepted only when the singleton ledger row and the complete final
shape verify.

`apply` holds the existing named session advisory lock across every phase and
rechecks quiescence inside every bounded transaction. A short preparation
transaction installs the new columns and write-time protections without
validating or promoting the final catalog. It then backfills committee,
candidate, filing, and transaction in UUID-keyset batches of at most 10,000
rows. Each batch and its progress checkpoint commit together under a 5-minute
statement timeout; a timeout or other failure rolls back only that bounded
transaction, so the same command resumes from the last durable UUID. The owner
does not skip locked rows.

For each backfill transaction, the owner locks and reads that relation's
durable `last_id`, then materializes only the next target primary-key IDs in
`id` order with the explicit cursor, `LIMIT 10000`, and `FOR UPDATE`. That
target-only batch is fixed before any authority-null filter or
`core.source_record` join. The owner updates only incomplete selected rows
that have a source record, while advancing `last_id` atomically to the maximum
selected target ID and counting selected target IDs as loop progress. Thus an
already-populated or source-less selected row still advances the cursor and
cannot strand a restart. The pinned migration artifact and its progress digest
remain unchanged; this is the existing owner's bounded execution contract.

Filing and transaction batches additionally materialize a cycle-safe recursive
closure over `amended_from_filing_id` ancestors and
`amended_by_transaction_id` successors. Recursion stops at 32 edges and the
distinct closure may contain at most 20,000 rows, including the original
maximum-10,000 target batch. Before any row or cursor change, every closure
edge must have source records whose `data_source_id` values agree with each
other and with any already-populated endpoint. A cycle, depth or closure
overflow, missing edge source, or actual scope mismatch rolls back the bounded
transaction. All incomplete closure rows are populated in one statement so
the existing AFTER STATEMENT amendment triggers observe both ends. The durable
cursor still advances only to the maximum ID in the original target batch;
dependency rows reached early are idempotently accepted when a later target
batch visits them.

After every backfill cursor reaches exhaustion, each final unique index is built with
`CREATE UNIQUE INDEX CONCURRENTLY` under its own 15-minute statement timeout.
Each check constraint is then validated in its own bounded transaction with
the same 15-minute statement timeout. Exact already-finished phases are
idempotently accepted; missing or drifted catalog state is either rebuilt only
when safe or refused.

After all nine expected indexes are valid and ready and all twelve checks are
validated, the owner commits one separate `READ ONLY` pre-cutover transaction
under the existing 15-minute bound. It rechecks quiescence, the empty final
ledger, exact columns, indexes, constraints, triggers, views, and progress,
then exhaustively proves native-identity semantics, provenance/scope refusal,
and complete backfills. A failure ends before any cutover DDL. The validated
checks, valid unique indexes, and write-time scope triggers prevent semantic
drift before the immediately following cutover.

The short final cutover transaction removes superseded catalog objects and the
transient progress table, records the original exact filename in
`core.schema_migrations` atomically, and verifies only the exact ledger, column,
constraint, index, trigger and trigger-function definitions, view, and transient catalog
state under the unchanged 5-minute statement timeout. It performs no domain
table scan while holding cutover locks. Any final mismatch rolls back the
cutover and ledger together. The chained post-commit `verify` invocation stays
read-only and exhaustive: as a standalone operation, it discards the identity
check's implicit transaction, then repeats the catalog proof plus every semantic,
provenance, refusal, and backfill scan in a fresh transaction-local `READ ONLY`
transaction after the cutover locks are gone. That transaction applies the
existing 15-minute per-statement timeout and 5-second lock timeout with `SET
LOCAL`; those settings reset when it commits or rolls back. This does not claim
a 15-minute total wall-time bound. A timeout fails closed without success JSON,
and the connection remains rollback-usable with its prior session timeout.

The existing migration ledger remains the only permanent completion
authority. Progress rows are resume cursors, not a second status or completion
registry, and disappear at cutover. A `partial_resumable` database therefore
never authorizes lifecycle, coverage, or public-claim promotion. Repeating
`apply` is idempotent only for that fully verified applied state. This
procedure is an execution contract, not production-write authorization.

## Authority-scoped regional scheduled-Machine profile (not provisioned)

`infra/fly/regional_refresh_machine_profile.json` is one strict authority
operations profile over the existing refresh registry. Its typed
`execution_plan` owns the exact authority identity, exact ordered scheduled job
keys, singleton canary, execution origins, stop-on-failure policy, Machine
cadence, cadence-clock owner, and both lock layers. It is neither another job
registry nor another scheduler. The checked-in profile remains the Washington
control and names the separate app `civibus-regional-refresh`; no regional
Machine may be added to `civibus-refresh`, whose exact-one-Machine federal
contract above remains unchanged. The profile asserts no live app, Machine, or
image.

The scheduled command is derived byte-for-byte from that profile:

```text
python -m core.refresh.runner --authority-plan-json infra/fly/regional_refresh_machine_profile.json --execution-mode scheduled --execution-origin scheduled
```

The runner loads the complete existing registry, refuses missing, duplicate, or
cross-authority scheduled ownership, and then selects the profile's exact order.
Planned execution rejects `--force`, `--dry-run`, `--no-lock`, selection flags,
and every extra option. The profile requires region `sjc`, default state
`stopped`, restart policy `no`, `auto_destroy=false`, shared one-vCPU/1GB shape,
no services, and the exact non-secret database environment. Its current daily
cadence is a profile value, not a runner constant.

The Machine-configuration identity is SHA-256
`620ad2707365938ba628433d254f8ef9d229a075c2c880435edc1f947379abad`
over canonical compact sorted JSON of `machine.config`. The full typed profile
identity is
`2f7fdbe1e97473479617212fa2cc6a22f6f4482011856f0583d9f757c2c4760f`.
Its accepted canonical receipt/source/tree are
`f198d2d2aab360b62d55d6b61f2853f4a4bc10ac`,
`3df2e919388edb84b9f4f6cc33c496a8a8462937`, and
`61c293365ede61e0a43d42087c0ffdd70251631f`. The image repository remains
`registry.fly.io/civibus-refresh`, while `image.tagged_digest` remains `null`.
Qualification must pull one exact `<tag>@sha256:<digest>` and prove inside it
the descendant candidate stamp plus the profile-derived authority, scheduled
plan, singleton canary, cadence clock, and concurrency contract. It then issues
an immutable candidate receipt before provisioning review.

The qualifier-issued regular, non-symlink receipt is the trust boundary for
lifecycle review. Preserve it externally and record its file SHA-256. Every
lifecycle action privately snapshots and hashes both receipt and profile before
validation, then derives the app, Machine, authority, plan, commands, and
resource-ownership markers from only those snapshots. Two authority profiles
must not share an authority, app, Machine, plan id, or scheduled job.

The authority Machine has no Fly volume or mount. Its refresh scratch root is
`/tmp/civibus-refresh-data`; authority downloaders must use bounded temporary
storage, and the federal scratch volume must not be reused. The only declared
runtime secret name is `POSTGRES_PASSWORD`, delivered as an app-level Fly
secret. Secret values, secret environment entries, Machine files, credential
paths, and `FLY_API_TOKEN` are forbidden in the profile and Machine config.

Normal terminal disposition retains only the exact owned Machine stopped.
Rollback may non-force-destroy an exact receipt-owned stopped Machine. If an
exact start-attempt marker exists and that Machine is started, rollback stops it
once, reverifies stopped, destroys it without force, verifies empty Machine and
volume inventories plus exact app/organization/authority/plan identity, and
then removes only the task-created app. Any running, ownership-drifted, or
indeterminate state requires handoff without mutation or retry. There is no
volume cleanup because a non-empty volume inventory blocks app removal.

This local-only command validates the frozen profile without Fly, secrets, or
database access:

```bash
bash infra/scripts/verify_refresh_machine.sh \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --profile-only
```

Omitting `--profile-only` fails closed without a candidate receipt and exact
live fixtures. A profile-only PASS is configuration evidence, not image or
execution evidence. The same deploy owner exposes a build-only authority image
qualification mode. It binds the clean candidate HEAD and tree from the
manifest into the build stamp, uses Fly's supported local build plus registry
push path, and requires authenticated registry metadata to resolve the exact
emitted tag to the exact emitted manifest digest. The digest owner accepts
Fly's exact current `<tag>: digest: sha256:... size: ...` summary as well as the
legacy full `tag@sha256` form; either form remains bound to the single full
image tag emitted by the same build. Only then does it pass that immutable
`tag@sha256` to the unchanged non-retrying qualifier, reuse the existing image
verifier, and remove its exact local image tag. This branch has no Machine,
app, secret, schedule, or lifecycle path:

```bash
bash infra/scripts/deploy_refresh_machine.sh --regional-build-qualify \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-manifest-json /absolute/evidence/candidate-manifest.json \
  --evidence-dir /absolute/evidence/empty-regional-build \
  --candidate-receipt-json /absolute/evidence/empty-regional-build/candidate-receipt.json
```

The existing qualifier remains available for an already produced exact image.
Both paths are qualification owners, not authority to mutate a Machine. The
same deploy owner also exposes the reversible authority lifecycle switch; the
historical `--regional-action` option name does not weaken profile scoping:

```bash
bash infra/scripts/deploy_refresh_machine.sh --qualify-only \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-manifest-json /absolute/evidence/candidate-manifest.json \
  --produced-image-tagged-digest 'registry.fly.io/civibus-refresh:<tag>@sha256:<digest>' \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json
bash infra/scripts/deploy_refresh_machine.sh --regional-action create-stopped \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json \
  --canary-promotion-json /absolute/evidence/completed-canary-lifecycle/regional_canary_promotion.json \
  --lifecycle-dir /absolute/evidence/lifecycle --secret-file /absolute/POSTGRES_PASSWORD.env
bash infra/scripts/deploy_refresh_machine.sh --regional-action start-once \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json \
  --lifecycle-dir /absolute/evidence/lifecycle
bash infra/scripts/deploy_refresh_machine.sh --regional-action rollback \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json \
  --lifecycle-dir /absolute/evidence/lifecycle
```

Before creating a retained recurring Machine, qualify the profile's singleton
canary in its own empty lifecycle directory. Its command is byte-exact and
operator-attended; loading the complete scheduled registry first prevents a
canary from masking a missing or cross-owned recurring job:

```text
python -m core.refresh.runner --authority-plan-json infra/fly/regional_refresh_machine_profile.json --execution-mode canary --execution-origin operator_attended
```

Use the lifecycle owner's canonical read-only invariance capture before the one
permitted start. It captures and validates the existing federal Machine owner,
the public API/web/content-health owners, and the explicit read-only database
identity and quiescence owner; callers do not create or pass snapshot JSON.
Then start once, prove the exact Machine's terminal stopped state and single
zero exit through the lifecycle owner, run the same canonical capture for the
post-run stage, retain the read-only ledger/freshness evidence, and remove the
canary app and Machine. The
lifecycle owner publishes an authority/plan-bound start-attempt marker before
starting, so a failed or indeterminate attempt cannot be retried. The runner
takes exact authority and job locks on both host and PostgreSQL and stops on the
first non-success result.

```bash
bash infra/scripts/deploy_refresh_machine.sh --regional-action create-canary-stopped \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR" \
  --secret-file "$REGIONAL_SECRET_FILE"

: "${REGIONAL_CANDIDATE_RECEIPT_JSON:?set the qualified candidate receipt path}" &&
: "${REGIONAL_LIFECYCLE_DIR:?set the retained canary lifecycle directory}" &&
: "${POSTGRES_HOST:?set the explicit read-only connection host}" &&
: "${POSTGRES_PORT:?set the explicit read-only connection port}" &&
: "${POSTGRES_USER:?set the explicit read-only connection user}" &&
: "${POSTGRES_DB:?set the explicit read-only database name}" &&
{ test -n "${POSTGRES_PASSWORD:-}" || test -n "${PGPASSFILE:-}"; } &&
bash infra/scripts/deploy_refresh_machine.sh --regional-action capture-invariance \
  --invariance-stage before \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR"

bash infra/scripts/deploy_refresh_machine.sh --regional-action start-canary-once \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR"

uv run python -m core.refresh.authority_ledger \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --proof-json "$REGIONAL_CANARY_LEDGER_PROOF_JSON"

bash infra/scripts/deploy_refresh_machine.sh --regional-action capture-invariance \
  --invariance-stage after \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR"

bash infra/scripts/deploy_refresh_machine.sh --regional-action start-canary-once \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR" \
  --authority-ledger-proof-json "$REGIONAL_CANARY_LEDGER_PROOF_JSON" \
  --refresh-postcondition-json "$REGIONAL_CANARY_DATABASE_POSTCONDITION_JSON"

bash infra/scripts/deploy_refresh_machine.sh --regional-action rollback \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
  --lifecycle-dir "$REGIONAL_LIFECYCLE_DIR"
```

`capture-invariance --invariance-stage before` is the only accepted producer
for the two pre-start snapshots. It requires the exact stopped, never-started
canary marker graph, an explicit database connection, `transaction_read_only`
and `default_transaction_read_only` both `on`, and zero running refresh rows,
refresh backends, long-idle transactions, ungranted locks, or advisory locks.
The `after` stage requires the exact terminal marker and evidence and refuses a
rollback boundary. Both stages publish the federal and public files atomically,
without overwrite, at mode `0600`; a repeat passes only when newly derived bytes
match the retained evidence. A partial, stale, replayed, foreign, split-revision,
unhealthy, write-enabled, nonquiescent, placeholder, or caller-authored snapshot
is RED before another lifecycle mutation. Passwords remain in the inherited
environment or mode-`0600` `PGPASSFILE`; they never appear in arguments or
published evidence.

The first `start-canary-once` invocation requires each canonical before snapshot
to be no more than ten minutes old (with at most one minute of future clock
skew) at the start-admission instant. Before the single start, its mode-`0600`
start-attempt marker durably records that admission instant plus the exact file
and semantic-identity hashes for both snapshots. It then atomically publishes
the terminal Machine evidence and terminal marker. It deliberately returns a
nonzero handoff status until the database, ledger, and after-invariance owners
exist. That status is not authority to start again. The second invocation
recognizes the same terminal marker and requires the retained before files to
match the admitted hashes and identity exactly; it does not re-age a baseline
that was proven fresh at start. The after snapshots must still be fresh at
finalization, and the admitted start-to-terminal window remains bounded at 30
minutes. It validates and atomically publishes the exact post-run owner files
and finalizes without issuing another `flyctl machine start`. Rollback captures
app/Machine/volume inventories before and after mutation and produces
`regional_canary_promotion.json` only when the complete graph is valid. An
already absent app produces the same exact zero inventories and markers without
issuing a Fly mutation.

### Historical orphaned refresh-attempt recovery

Use this path only after the Machine or process that created one exact committed
`running` row is absent and read-only evidence proves no refresh backend owns
it. Do not call `_fail_started_attempt`, issue a manual `UPDATE`, retry the old
canary, or create a replacement Machine. `core.refresh.runner` is the only
mutation owner: it validates every supplied identity, proves quiescence, takes
the existing `civibus-refresh-runner:<job_key>` PostgreSQL advisory lock, locks
the exact row with `FOR UPDATE NOWAIT`, re-reads and re-proves inside the
transaction, and updates only that `core.refresh_run` row.

Populate every variable from the retained read-only attempt, Machine, profile,
and database receipts. Values below are deliberately variables rather than a
copyable historical specimen. The configured `POSTGRES_HOST`, `POSTGRES_PORT`,
and `POSTGRES_DB` must be byte-identical to the expected database identity; use
the authorized database-local runtime whose identity the regional lifecycle
profile expects. Keep `POSTGRES_PASSWORD` in the existing non-argv credential
channel.

```bash
: "${RECOVERY_REFRESH_RUN_ID:?exact historical core.refresh_run id}" &&
  : "${RECOVERY_JOB_KEY:?exact historical job key}" &&
  : "${RECOVERY_STARTED_AT:?exact timezone-aware started_at}" &&
  : "${RECOVERY_DATA_SOURCE_NAME:?exact historical data-source name}" &&
  : "${RECOVERY_MACHINE_ID:?exact creating Machine id}" &&
  : "${RECOVERY_POSTCONDITION_JSON:?new external evidence path}" &&
  : "${POSTGRES_HOST:?expected database host}" &&
  : "${POSTGRES_PORT:?expected database port}" &&
  : "${POSTGRES_DB:?expected database name}" &&
  python -m core.refresh.runner \
    --recover-refresh-run-id "$RECOVERY_REFRESH_RUN_ID" \
    --recover-job-key "$RECOVERY_JOB_KEY" \
    --recover-domain campaign_finance \
    --recover-jurisdiction state/WA \
    --recover-filing-authority-type state \
    --recover-filing-authority-code WA \
    --recover-data-source-name "$RECOVERY_DATA_SOURCE_NAME" \
    --recover-execution-origin operator_attended \
    --recover-started-at "$RECOVERY_STARTED_AT" \
    --recover-app civibus-regional-refresh \
    --recover-machine-id "$RECOVERY_MACHINE_ID" \
    --recover-authority state/WA \
    --recover-execution-plan regional-wa-scheduled \
    --recover-database-host "$POSTGRES_HOST" \
    --recover-database-port "$POSTGRES_PORT" \
    --recover-database-name "$POSTGRES_DB" \
    --recover-postcondition-json "$RECOVERY_POSTCONDITION_JSON"
```

The complete option set is exclusive: mixing normal runner options, omitting
one identity, duplicating a singleton option, or supplying a naive timestamp
is a refusal before connecting. The database path also refuses a missing or
foreign row; job, domain, jurisdiction, ordered source-set, filing-authority,
execution-origin, or `started_at` drift; ambiguous source rows; any other
running refresh row; an exact or conflicting refresh backend; a long-idle
transaction; an ungranted lock; advisory or row-lock contention; a row or
source identity that changes after preflight; and any terminal outcome not
written by this exact recovery owner.

On an exact match, the owner atomically records `pull_status=failed`, a
timezone-aware `completed_at`, zero loader counts, and `metadata_updates=0`
with explicit historical-interruption evidence. It never invokes a job,
updates `core.data_source`, promotes source freshness, or writes campaign
finance domain data. A repeated complete invocation recognizes only its own
byte-exact terminal evidence and recreates the same postcondition without
changing history. An existing different postcondition file is never
overwritten.

The output file is canonical sorted JSON with the existing regional lifecycle
postcondition shape: exact app, Machine, authority, plan, attempt, job,
execution origin, terminal status/time, metadata count, database identity,
`running_refresh_rows=0`, and `active_refresh_backends=0`. Preserve its SHA-256
with the read-only pre/post evidence, then pass that exact regular non-symlink
file to the existing lifecycle owner:

```bash
bash infra/scripts/deploy_refresh_machine.sh --regional-action rollback \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json \
  --lifecycle-dir /absolute/evidence/retained-canary-lifecycle \
  --expected-refresh-run-id "$RECOVERY_REFRESH_RUN_ID" \
  --refresh-postcondition-json "$RECOVERY_POSTCONDITION_JSON"
```

The exact attempt option binds the postcondition to the retained recovery
identity; a different otherwise-well-formed attempt is refused. If the exact
regional app is already absent, this same rollback action validates the exact
retained create/Machine/provision/canary/start/rollback marker chain, proves
unambiguous app-inventory absence, and publishes only the missing mode-0600
`rollback_stopped.json` and `rollback_complete.json` receipts. It performs no
Machine or app mutation and repeats idempotently only against those same exact
receipts. A present or ambiguous app, missing or drifted marker, unexpected
canary-terminal marker, or non-failed/nonzero/foreign postcondition is RED.

Only that lifecycle command may consume the result for cleanup or subsequent
operations. A recovered failed attempt is not canary success and cannot
authorize recurring provisioning, lifecycle or coverage promotion, a public
claim, or another canary generation by itself.

The ledger proof is strict JSON with schema version, authority, plan id, exact
plan digest, mode, observation boundary, observed plan-row count, ordered runner
results, exact `core.refresh_run` rows, and baseline/post `core.data_source`
evidence. Construct it only from read-only
queries using the plan's authority, job, and data-source identities; retain the
queries and raw output beside it. The validator independently rebuilds the
existing registry. A canary is GREEN only for the exact singleton success,
operator-attended ledger row, exact metadata-update count, no sibling result,
and strictly advanced exact-source freshness. Scheduled proof requires every
plan key in exact order, allows only `success` or explicit cadence `skipped`,
and matches every success to one scheduled-origin ledger row. A proof cannot be
reused by another authority or plan. Any mismatch is RED and blocks recurring
provisioning. After GREEN cleanup, use a new empty lifecycle directory with
`create-stopped` and pass the exact completed
`regional_canary_promotion.json`. A standalone database postcondition cannot
replace this artifact. Its unattended job order and `stop_on_failure` value
continue to come only from the profile.

The secret file must be a mode-`0600`, non-symlink file containing exactly one
`POSTGRES_PASSWORD=...` assignment. Its value goes to Fly on stdin and never
appears in arguments or receipts. Before either stopped create can inspect or
create an app, stage that secret, or create a Machine, the lifecycle owner
authenticates to the registry, resolves the receipt's exact tag again, and
requires its digest to remain byte-exact. A missing tag or changed digest fails
closed without production mutation; rebuild or requalification is a separate
owner action. These commands require separate Fly mutation authority; none is
granted by this runbook. The verifier's no-profile invocation and the deploy
owner's default Machine-update path remain byte-for-byte hard-pinned to the
federal app and Machine.

### Regional unattended scheduler observation

Do not call `start-once` for the retained recurring regional Machine. After all
four profile jobs are due, the production observer captures read-only,
timestamped Fly app status, Fly Machine status, and database evidence from the
Machine-creation boundary through its terminal state. The observation JSON must
bind those three regular non-symlink files by absolute path, SHA-256, and capture
time; bind the exact profile and candidate-receipt file digests; and record the
exact app, Machine id/name, database identity, scheduler-or-host start event,
stopped zero-exit terminal event, ordered runner results, matching scheduled
refresh rows, exact source clocks, and zero running rows, active backends,
long-idle transactions, and ungranted locks.

Assemble and validate the regional receipt offline through the existing
authority-ledger owner:

```bash
uv run python -m core.refresh.authority_ledger \
  --profile-json infra/fly/regional_refresh_machine_profile.json \
  --raw-fly-app-status-json /absolute/evidence/raw-fly-app-status.json \
  --raw-fly-machine-status-json /absolute/evidence/raw-fly-machine-status.json \
  --raw-database-observation-json /absolute/evidence/raw-database-observation.json \
  --candidate-receipt-json /absolute/evidence/candidate-receipt.json \
  --observation-output-json /absolute/evidence/regional-scheduled-observation.json \
  --proof-output-json /absolute/evidence/regional-scheduled-ledger-proof.json \
  --receipt-output-json /absolute/evidence/regional-scheduled-observation-receipt.json
```

The builder performs no Fly or database call. It independently rebuilds the
registry, anchors the window to Machine creation, permits only a
scheduler/host-originated start, and requires the same Machine to stop once with
exit code zero. It parses—not merely hashes—the three raw owner-format JSON
captures. App status must contain the exact regional app and singleton Machine;
Machine status must bind the exact qualified image, name, config digest,
creation time, and ordered scheduler/host start plus stopped-zero-exit events;
database observation must bind that Machine, typed authority, plan, exact
database, ordered results/refresh UUIDs/source clocks, and all four zero
quiescence counters. Placeholder JSON and a correctly rehashed foreign capture
are both RED. Unlike the reusable scheduled ledger validator, this NP0 receipt
requires all four profile-ordered results to be `success`; cadence skips do not
qualify. Every result must have one `execution_origin=scheduled` terminal row,
exact registry-owned source names, exact metadata advancement, and a current
successful source clock. Missing, foreign, reordered, ambiguous, nonterminal,
nonzero, user/operator-originated, non-success, non-quiescent, stale, or
hash-drifted evidence is RED. The observation, proof, and receipt are canonical
sorted JSON, created atomically at distinct mode-`0600` paths without
overwriting an existing path.

The raw-owner mode is the callable observation producer. It derives the
observation fields from the three owner formats; do not manually copy Machine,
event, result, freshness, database, or quiescence values into an observation.
The receipt binds the nonempty expected Machine ID plus the candidate receipt,
source, tree, image, profile, plan, database, and exact ordered four terminal
attempt UUIDs, preventing a prior canary or another recurring Machine from
being replayed into admission.

After the changed serving revision passes its deploy parity and production
browser gates, the production evidence owner may assemble one strict authority
promotion receipt. It must name the typed geographic subject and the distinct
typed filing authority, keep the aggregation disposition `not_applicable` for
the single Washington authority, and carry exact ordered freshness, scheduled
recurrence, provenance, Keel, deployed-source, and equal API/web revision
evidence bound to the exact serving source revision. It must also reference
exactly these canonical artifacts, in order,
by absolute regular non-symlink path and SHA-256: canary ledger, unattended
recurrence, filing-authority decision, provenance, Keel, serving deploy, and
surface parity. The unattended-recurrence artifact is a strict manifest for the
mode-`0600` authority-ledger proof and regional observation receipt emitted by
the command above; it binds both output paths and byte digests. The serving
deploy artifact carries the candidate-receipt digest shared with that regional
receipt plus one equal source/API/web revision.

The receipt loader re-hashes every outer artifact, both Gate 10 outputs, all
three raw scheduled captures, and the canary candidate/terminal/postcondition,
invariance, inventory, and lifecycle-marker graph. It parses each artifact
through its strict owner schema and validates the canary and scheduled proofs
against the exact repository-owned Washington profile/plan/app/Machine/database
contract. The canary postcondition requires zero running refresh rows, active
refresh backends, ungranted locks, and long-idle transactions under the exact
database identity; rollback requires the exact marker chain and zero regional
app/Machine/volume inventory. It derives the typed authority,
four profile-ordered source identities, source clocks, scheduled completion
times, provenance scope, Keel set, deployed set, and source/API/web revision
from those artifacts. Self-asserted composite fields that are not byte- and
value-derivable from the canonical artifacts are refused.

For a promotion-bundle deploy, `deploy.yml` obtains the candidate receipt/tree,
qualified image, federal-invariance identity, and bundle digest only from the
already validated staged bundle. The existing HTTP parity probe atomically
publishes `raw-api.json`; the production `state_detail.spec.ts` oracle requires
fresh Washington `available` status and atomically publishes
`raw-browser.json`. The lifecycle CLI consumes those two mode-`0600` raw files
and produces the existing `surface-parity.json`, which the pinned artifact
upload step preserves with them. The producer requires equal source/API/web
revision, 18 ordered public surfaces, healthy API/content status, the exact
three regional routes, four Washington specimens, exact authority and
candidate identities, federal invariance, and a 30-minute observation window.
Missing, degraded, stale, partial, reordered, replayed, or correctly rehashed
foreign evidence fails the deploy and triggers the existing serving-image
rollback. Restoring the prior API image also restores its prior immutable
evidence bundle.

The existing read-only status command and regional API consume the same receipt
path through one environment owner:

```bash
CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON=/absolute/evidence/authority-promotion-receipt.json \
  make region-status REGION=WA
```

The API runtime uses `CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON` only after the
production owner stages that exact receipt and its referenced evidence. Both
readers independently derive the current source clocks and scheduled recurrence
rows and require byte-equivalent typed evidence before emitting
`promotion_eligible=true`. An absent, unreadable, symlinked, partial, foreign,
stale, non-scheduled, split-revision, hash-drifted, or current-clock-mismatched
receipt remains RED. This runtime evidence input does not edit the coverage or
lifecycle registries, does not combine state/county/municipal totals, and does
not authorize a production mutation.

### Stage promotion evidence in the serving API image

The serving deploy accepts promotion evidence only as one immutable GitHub
Actions artifact from an already completed run in the canonical production
repository. The artifact contains exactly one regular file named
`authority-promotion-bundle.tar`. The tar begins with the embedded
`authority-promotion-bundle-build-receipt.json`, followed by the receipt, the
exact seven ordered canonical artifacts, and only their transitively referenced
canary, scheduled, and raw parity evidence. The embedded build receipt binds the producer
run ID, `deploy.yml` run name, output artifact name, equal source/API/web
revision, and exact ordered path/SHA-256/mode tuple for every following member.
Every tar member is a regular mode `0600` file. Member names are relative paths rooted at
`app/private/civibus/authority-promotion`; the JSON keeps the corresponding
absolute `/app/private/civibus/authority-promotion/...` paths that the runtime
will read. Do not include credentials, secrets, symlinks, hardlinks, extra
files, or a second archive.

The callable producer is the non-production `promotion_bundle` job in the same
committed `deploy.yml` owner. Its source artifact must contain exactly the
validated `/app/private/civibus/authority-promotion` evidence tree—no extra
files—and the source run must already be complete. Dispatch it with the source
coordinates and desired immutable output name:

```bash
gh workflow run deploy.yml --repo gridl-hq/civibus \
  --ref main \
  -f authority_promotion_evidence_run_id="$EVIDENCE_RUN_ID" \
  -f authority_promotion_evidence_artifact_name="$EVIDENCE_ARTIFACT_NAME" \
  -f authority_promotion_bundle_artifact_name="$PROMOTION_ARTIFACT_NAME"
```

The producer uses pinned v4 download/upload Actions, invokes the lifecycle
receipt builder, and uploads only the exact tar. It has no production
environment, Fly token, registry, database, scheduler, or deployment access.
The serving production owner then passes only the completed producer run ID and
its exact output artifact name when dispatching the deploy consumer; never pass
receipt or artifact bytes in argv:

```bash
gh workflow run deploy.yml --repo gridl-hq/civibus \
  --ref main \
  -f authority_promotion_artifact_run_id="$PROMOTION_ARTIFACT_RUN_ID" \
  -f authority_promotion_artifact_name="$PROMOTION_ARTIFACT_NAME"
```

The workflow requires the two inputs together, downloads exactly that artifact,
requires the embedded run ID/name/artifact name to match those immutable
coordinates, and calls the lifecycle owner before the first serving deploy. The lifecycle
owner safely expands the tar into a temporary virtual root, re-hashes and
strictly derives every canonical and nested artifact, requires exact
`state/WA`, the profile-ordered source set, and source/API/web revision equality
with the validated Debbie `dev_sha`, rejects unreferenced files, and only then
materializes the byte-identical bundle in the API build context. Any missing,
extra, reordered, symlinked, hardlinked, wrong-mode, wrong-schema,
foreign-scope, stale/degraded, split-revision, digest-drifted, or
self-asserted/non-derivable input stops before `flyctl deploy`.

The API Dockerfile installs the validated bundle at
`/app/private/civibus/authority-promotion`, normalizes directories to mode
`0555` and files to mode `0444`, and keeps them owned by root. On normal API
startup, the image entrypoint sets
`CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON` to
`/app/private/civibus/authority-promotion/authority-promotion-receipt.json`
only when that image contains the regular non-symlink receipt. An ordinary
push or dispatch with neither artifact input retains pre-promotion behavior and
leaves the environment unset. `api.fly.toml` never owns or overrides this path,
and no runtime fetch or shared writable bundle exists.

Serving rollback remains the existing image rollback. The captured
`civibus-api` image contains its own code, evidence bytes, and entrypoint
binding, so restoring it also restores the prior API image's prior evidence
bundle atomically. Never inject promotion evidence with Fly `--file-local`, a
volume, a secret, or a manual copy; those forms can make old code observe new
evidence after rollback.

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

`core/refresh/runner.py` is the same-job serialization owner. It takes a local
per-job-key `flock` before opening PostgreSQL, then takes a nonblocking,
session-scoped PostgreSQL advisory lock for each exact selected job key before
writing a refresh receipt or calling a job. No normal refresh job class requires
database-wide quiescence. If a future job class needs global quiescence, this
section must name both its owner and the reason. The writer preflight and the
scheduler's "zero other running Civibus lanes" attribution rule above are
distinct: the latter identifies the source of a scheduler event and must not be
removed as a global writer gate.

> Regional campaign-finance refresh writes have no single fixed execution host.
> The scheduled Machine `859e0da479e678` is pinned to `python -m
> core.refresh.runner --scope federal` and never runs a regional
> `--job-key-prefix` key; regional writes are launched operator-attended via
> `make refresh-cf-data` over a local `flyctl proxy` from a workstation, or from
> an ephemeral `flyctl machine run --rm` machine. The runner's local
> `fcntl.flock` guard (`_RUNNER_LOCK_PATH` and
> `_runner_lock_path_for_job_key`) still serializes only one host and lock base.
> Cross-host exclusion comes from `_try_acquire_database_runner_locks`, held on
> the `refresh:runner` PostgreSQL session under the stable namespace
> `civibus-refresh-runner:<exact job key>`. A scheduled regional Machine and an
> operator-attended run therefore contend when their exact selected keys
> overlap. The federal Machine's `--scope federal` keys remain disjoint from
> regional keys and intentionally continue concurrently. The regional selector
> is exactly `state-wa-`; all four keys acquire both lock layers and release
> them after success, degradation, or failure.

Every production runner that can write the shared database must retain both
guards. `--no-lock` deliberately bypasses them for debugging, and direct callers
of `run_all_jobs()` remain responsible for their own exclusion. Job-owned
connections continue to use `application_name = 'refresh:<job_key>'`; the
long-lived lock holder uses `refresh:runner`.

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
The 2026-08-25 watch was terminal `AUTOMATIC_REFRESH_RED` at the same
no-other-running-Civibus-lane attribution gate
(`docs/live-state/2026_08_25_refresh_scheduler_boundary.md`).

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

The retired bootstrap procedure is preserved in [Retired VM Bootstrap and Checkout](./campaign_finance_refresh_retired_vm.md#bootstrap-production-vm).

### Production checkout path

The retired checkout-path contract is preserved in [the same reference](./campaign_finance_refresh_retired_vm.md#production-checkout-path).

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
- Process exits `2` without running any job when another runner holds an overlapping local or database job lock, or when neither local lock path can be opened. Exit `2` therefore means "nothing ran", not "a job failed"; no `core.refresh_run` receipt is written for it.

### Per-job runner locks and `--lock-wait-seconds`

`core/refresh/runner.py` takes one exclusive `flock` per distinct job key in the
plan. A typed authority execution additionally takes
`authority-plan:<kind>/<code>`, so two plans cannot share exact authority
ownership even if their job lists are accidentally disjoint. Paths are derived
by `_runner_lock_path_for_job_key()` from
`/var/lock/civibus-refresh-runner.lock`, falling back to
`_fallback_runner_lock_path()` (`$TMPDIR/civibus-refresh-runner-<uid>.lock`) where
`/var/lock` is not writable, as on macOS dev hosts. Contention is therefore
per key: a narrowly scoped run competes only with same-host runs whose plan
shares one of its job keys, including a `--scope all` run that covers them. The
authority key adds ownership isolation without creating a global scheduler
lock.

After all local locks succeed, the runner opens its orchestration connection
and calls PostgreSQL `pg_try_advisory_lock(hashtextextended(<name>, 0))` once
for each of the same sorted, distinct lock keys. `<name>` is
`civibus-refresh-runner:<exact job key>` or
`civibus-refresh-runner:authority-plan:<kind>/<code>`. These are session locks, not
transaction locks: they survive the committed `running` receipt and later
per-job commits and rollbacks, and PostgreSQL releases them when the runner
connection closes. Contention closes that connection, releases any earlier
database locks plus every local file descriptor, and exits `2` before ledger or
job execution.

By default acquisition does not wait. Local contention prints
`Another refresh runner is already active (lock: <path>)`; database contention
names the exact job as `database lock: <job_key>`. Both paths release their
earlier locks and exit `2`. An operator-attended run for one planned job still
contends with the scheduled Machine through the exact job key. Plans for two
different authorities share neither ownership nor job keys, and fixtures prove
their local and database lock sets are disjoint. Pass `--lock-wait-seconds <n>` to queue for the
same-host file locks instead of being dropped; the wait budget applies to each
local key separately. Database advisory-lock contention remains nonblocking.
The value must be finite; `inf`/`nan` are rejected at argument parsing:

```bash
REFRESH_CF_ARGS='--job-key-prefix state-pa-expenditures --pa-year 2026 --force --lock-wait-seconds 1800' \
  make refresh-cf-data
```

Retrying by hand against a busy host is a race; the bounded wait is the supported
way to get a narrow job through. Default `0` keeps the fail-fast behavior for cron
and wrapper callers, which must not stack up behind each other.

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
