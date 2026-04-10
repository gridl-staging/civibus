<!-- [scrai:start] -->
## civics

| File | Summary |
| --- | --- |
| ingest.py | Shared canonical upsert helpers for civic domain entities.

Each function takes a psycopg Connection and a Pydantic model instance,
performs INSERT .. |

| Directory | Summary |
| --- | --- |
| graph | This graph module loads civic domain relational data into Apache AGE by materializing key edges (HOLDS, RUNS_IN, CANDIDACY_OF, REPRESENTS) that connect civic entities in the knowledge graph. |
| tests | This tests directory contains a utility module that provides factory functions for building valid test payloads for civic domain models like offices, electoral divisions, contests, candidacies, and officeholdings. |
| types | Canonical Pydantic models for civic domain entities: Office, ElectoralDivision, Contest, Candidacy, and Officeholding. |
<!-- [scrai:end] -->
