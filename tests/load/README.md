# Load Testing

This directory contains a minimal Locust harness that targets the public Civibus API routes.

## Prerequisites

1. `make db-up`
2. `make db-reset`
3. `make ingest-fec-bulk-sample`
4. `POSTGRES_PASSWORD=... CIVIBUS_API_KEYS=... CIVIBUS_RATE_LIMIT_REQUESTS=100 CIVIBUS_RATE_LIMIT_WINDOW_SECONDS=60 make api-dev`

## Required Environment Variables

- `CIVIBUS_API_KEYS`: comma-separated API keys used by the API (`X-API-Key` uses the first key)
- `CIVIBUS_RATE_LIMIT_REQUESTS`: positive integer request budget required by `api.main.create_app()`
- `CIVIBUS_RATE_LIMIT_WINDOW_SECONDS`: positive integer window size required by `api.main.create_app()`
- `POSTGRES_PASSWORD`: required by `make db-up`, `make db-reset`, and `make api-dev`

## Commands

Headless smoke run:

```bash
make load-test
```

Headless run with custom users and duration:

```bash
uv run --extra load locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 2m
```

Web UI mode:

```bash
uv run --extra load locust -f tests/load/locustfile.py --host http://127.0.0.1:8000
```
