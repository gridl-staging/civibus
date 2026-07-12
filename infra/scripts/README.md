# Infra Scripts

These scripts are the checked-in automation surface for local database operations and
production-host bootstrap. They should stay aligned with the runtime contracts already
owned by `Makefile`, Compose, workflows, and `.env.production.example`.

## Runtime Contract Sources

- `Makefile`
- `.github/workflows/deploy.yml`
- `.env.production.example`
- `infra/docker-compose.yml`
- `infra/docker-compose.prod.yml`
- `core/db.py`
- `core/docker_compose.py`

## Production Host Bootstrap

`bootstrap_prod_vm.sh` is the first-boot production helper. It is designed to run on
the target VM as `root` and must remain idempotent. Current responsibilities:

- install base packages required for deploy (`ca-certificates`, `curl`, `git`, `gnupg`)
- install Docker Engine + Compose plugin when absent
- ensure the production checkout exists at `/root/civibus/civibus_dev`
- materialize `/root/civibus/civibus_dev/.env` from an injected env-file payload
- fail fast when required runtime keys are missing

The GitHub Actions deploy workflow is the canonical caller for this script. Local agent
sessions may also use it when they have the same authorized SSH + secret material.

## Long-Running Dispatch Contract

`long_running_dispatch.sh` is the generic wrapper for launching long-running background
commands while writing deterministic dispatch metadata.

```bash
./infra/scripts/long_running_dispatch.sh \
  --log-path docs/reference/research/artifacts/<run>/dispatch.log \
  --metadata-path docs/reference/research/artifacts/<run>/dispatch_metadata.json \
  -- uv run python -m core.entity_resolution.tuning --candidate-id c1
```

Dispatch failure means the wrapper itself could not start a child process and record
its PID/metadata. Child-process failure happens after successful dispatch (including
short-lived exits) and must be diagnosed from the log.

## Prerequisites

1. Export `POSTGRES_PASSWORD` in your shell.
2. Start the local database:

```bash
POSTGRES_PASSWORD=... make db-up
```

## Backup

Run:

```bash
POSTGRES_PASSWORD=... ./infra/scripts/backup.sh
```

Output dumps are written to `infra/scripts/backups/` using `<database>-<utc-timestamp>.dump`.

## Restore

Restore requires an explicit dump path and explicit overwrite confirmation:

```bash
POSTGRES_PASSWORD=... ./infra/scripts/restore.sh infra/scripts/backups/<dump-file>.dump --yes-overwrite-local-db
```

Restore overwrites the current local database.
