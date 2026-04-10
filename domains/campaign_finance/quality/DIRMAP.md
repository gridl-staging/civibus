<!-- [scrai:start] -->
## quality

| File | Summary |
| --- | --- |
| __init__.py | Campaign finance data quality checks and reconciliation framework. |
| __main__.py | Allow running as python -m domains.campaign_finance.quality. |
| checks.py | Anomaly detection checks for campaign finance data quality.

Orchestration-only: calls shared helpers from reconciliation.py,
evaluates threshold rules, and emits CheckResult models. |
| cli.py | Stub summary for cli.py. |
| closeout_evidence_base.py | Shared closeout evidence behavior for federal and state modules.

Eliminates duplication of surfaced_anomalies(), to_json(), utc_now(),
and write_evidence_artifact() across fec_closeout_models.py and
state_closeout_models.py. |
| fec_closeout.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/quality/fec_closeout.py. |
| fec_closeout_models.py | Pydantic models for Stage 2 federal FEC closeout evidence artifacts. |
| freshness.py | Stub summary for freshness.py. |
| models.py | Pydantic result models for quality checks and reconciliation.

These models define the single JSON schema consumed by the CLI.
Do not create separate contract documents — this module is the source of truth. |
| reconciliation.py | Provenance-driven reconciliation checks.

Stateless functions that accept a psycopg connection, query
core.data_source / core.source_record, and return model instances. |
| schedule_e_closeout.py | Schedule E independent-expenditure closeout module.

Orchestrates scoped quality checks on Schedule E source records within
the shared federal/fec data source. |
| schedule_e_closeout_models.py | Pydantic models for Schedule E independent-expenditure closeout evidence. |
| state_closeout.py | Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/quality/state_closeout.py. |
| state_closeout_models.py | Pydantic models for Stage 3 state closeout evidence artifacts.

Mirrors the federal FEC closeout model structure but carries state-specific
evidence sections for CO, GA, and NC. |
<!-- [scrai:end] -->
