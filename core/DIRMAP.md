<!-- [scrai:start] -->
## core

| File | Summary |
| --- | --- |
| db.py | Database access layer providing connection management and row serialization for core entity types (Person, Organization, Address, DataSource, SourceRecord). |
| db_ingest.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/core/db_ingest.py. |
| docker_compose.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_cross_domain_er_and_property_graph/civibus_dev/core/docker_compose.py. |
| schema_sql_runner.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_cross_domain_er_and_property_graph/civibus_dev/core/schema_sql_runner.py. |

| Directory | Summary |
| --- | --- |
| entity_resolution | Core entity resolution module using Splink to identify and deduplicate entities across records, with utilities for persisting relational state, generating deterministic proof payloads, and loading matched entities into the knowledge graph. |
| graph | The graph directory provides tools and utilities for managing Apache AGE knowledge graph operations, including CLI commands for graph manipulation, data loaders for populating nodes and edges from campaign finance and other domains, and test support utilities for validating graph operations. |
| refresh | The refresh directory contains the orchestrator for automated campaign finance data ingestion, which builds and executes refresh jobs for nine state jurisdictions and FEC federal data according to configured update cadences. |
| types | The types module defines the shared data models and plugin contract that domain extractors use to ensure consistent entity representation across the Civibus platform. |
<!-- [scrai:end] -->
