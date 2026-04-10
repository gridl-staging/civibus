<!-- [scrai:start] -->
## api

| File | Summary |
| --- | --- |
| __init__.py | API package for FastAPI app entrypoints and routers. |
| main.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/api/main.py. |
| queries_graph.py | Graph query helpers for Apache AGE entity relationship lookups. |

| Directory | Summary |
| --- | --- |
| middleware | The middleware directory contains access control and logging modules for the FastAPI application. |
| models | Pydantic response models for the Civibus API across three domains: campaign finance, civics (offices, contests, candidacies, officeholdings), and property. |
| queries | The queries package encapsulates domain-specific SQL constants, database fetchers, and shared query utilities for accessing the civibus platform's PostgreSQL database across campaign finance, civic, entity resolution, property, and search domains. |
| routes | The routes directory contains FastAPI endpoint definitions for the Civibus API, including campaign finance and civics domain endpoints that expose offices, contests, candidacies, officeholdings, and contacts. |
<!-- [scrai:end] -->
