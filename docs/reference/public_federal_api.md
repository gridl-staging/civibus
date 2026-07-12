# Public Federal API

The public federal API is available under `/public/v1` and does not require an API key.

This surface is read-only, nonpartisan, source-linked, and federal-only. It covers current federal officials and their FEC money / independent-expenditure summaries. The machine-readable contract is the FastAPI schema at `/openapi.json`; the interactive reference is `/docs`.

Public responses are IP rate limited by the shared fixed-window API limiter. Responses carry `Cache-Control: public, max-age=900`.

## Endpoints

### Current Federal Officials

`GET /public/v1/federal/officials`

Returns the current federal-official directory. Optional filters are `chamber`, `state`, and `party`.

```bash
curl -fsS 'http://127.0.0.1:8000/public/v1/federal/officials?state=NC'
```

### Member Money Summary

`GET /public/v1/federal/officials/{person_id}/money`

Returns the FEC money and independent-expenditure summary for one current federal official. Unknown `person_id` values return 404; known officials without linked FEC money return 200 with `has_fec_money: false`.

```bash
curl -fsS 'http://127.0.0.1:8000/public/v1/federal/officials/00000000-0000-0000-0000-000000000000/money'
```

### JSON Export

`GET /public/v1/federal/export.json`

Returns the public money summary rows as JSON.

```bash
curl -fsS 'http://127.0.0.1:8000/public/v1/federal/export.json'
```

### CSV Export

`GET /public/v1/federal/export.csv`

Returns the public money summary rows as CSV. The frozen column order is owned by `PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS` in `api/routes/public_federal.py`.

```bash
curl -fsS 'http://127.0.0.1:8000/public/v1/federal/export.csv'
```
