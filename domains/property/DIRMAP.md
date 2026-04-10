<!-- [scrai:start] -->
## property

| File | Summary |
| --- | --- |

| Directory | Summary |
| --- | --- |
| entity_extractors | Extracts Person, Organization, and Address entities from Durham ArcGIS parcel records for knowledge graph population and entity resolution. |
| graph | Loads property domain relationships (ownership, location, zoning, assessment) into the Apache AGE knowledge graph, creating and linking Parcel, Jurisdiction, ZoningClass, and Assessment nodes with provenance tracking. |
| ingest | The ingest directory contains the data pipeline for the property domain, with modules for Durham-specific property sources, command-line utilities, a data loader, and test helpers. |
| jurisdictions | — |
| normalize | Provides Durham property owner normalization utilities including classification (person vs organization), joint-owner splitting, name cleanup with title-casing, and mailing-address standardization from raw owner fields. |
| tests | Test utilities for the property domain, including package markers and shared payload builders for constructing test fixtures and validating property model behavior. |
| types | The types directory contains property domain type definitions and model exports, serving as the shared type contract for the property domain plugin. |
<!-- [scrai:end] -->
