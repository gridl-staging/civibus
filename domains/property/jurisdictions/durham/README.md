# Durham Property Source

This directory is the source of truth for Durham County property ingest assets:

- `config.yaml`: Durham jurisdiction metadata and ArcGIS source contract.
- `fixtures/sample_query_response.json`: small ArcGIS response sample for local ingest and tests.

Stage 5 ingest code reads these assets through `domains.property.ingest.durham_source`
so the loader, CLI, and Makefile entrypoint do not duplicate Durham constants.
