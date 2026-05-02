POSTGRES_USER ?= civibus
POSTGRES_DB ?= civibus
POSTGRES_PORT ?= 5433
WORKSPACE_SLUG := $(shell basename "$$(dirname "$(CURDIR)")" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_$$//')
COMPOSE_PROJECT_NAME ?= civibus_$(WORKSPACE_SLUG)

export POSTGRES_USER
export POSTGRES_PASSWORD
export POSTGRES_DB
export POSTGRES_PORT
export COMPOSE_PROJECT_NAME

DB_HOST := localhost
# Keep the schema reset manifest repo-owned: db-reset interpolates this list into
# shell and Python recipe bodies, so command-line overrides would become code execution.
DB_SQL_FILES := core/schema/entities.sql core/schema/jurisdiction.sql core/schema/provenance.sql core/schema/entity_resolution.sql core/schema/er_views.sql domains/campaign_finance/schema/tables.sql domains/campaign_finance/schema/nc_orchestrator_tables.sql domains/campaign_finance/schema/dark_money_tables.sql domains/property/schema/tables.sql domains/civics/schema/tables.sql infra/db/09-age-graph-bootstrap.sql
FEC_BULK_CYCLE ?= 2024
FEC_BULK_DIR ?= data/fec/bulk/$(FEC_BULK_CYCLE)
IRS_527_DATA_DIR ?= data/irs_527
IRS_527_PATH ?= $(IRS_527_DATA_DIR)/FullDataFile.txt
IRS_527_BATCH_SIZE ?= 1000
REFRESH_CF_ARGS ?= --dry-run
QUALITY_CHECK_ARGS ?=
QUALITY_FRESHNESS_ARGS ?=
RETIRED_SYMBOLS := INDIANA_FRESHNESS_NOTE _CASE_FIXTURE_SOURCES _PILOT_SUPPORTED_STATES is_autopublish_enabled
RETIRED_ALLOWLIST := \
	core/keel_gate_l11.py \
	tests/keel/test_gate_l15.py \
	docs/keel/** \
	chats/** \
	.matt/projects/** \
	Makefile


.PHONY: db-up db-down db-reset test test-api test-e2e lint check-retired-symbols ingest-fec-sample ingest-fec-bulk-sample ingest-fec-bulk ingest-fec-ie-sample download-fec-bulk download-fec-schedule-e ingest-fec-schedule-e download-irs-527 ingest-irs-527-sample ingest-irs-527 validate-configs validate-registry render-coverage-views render-region-lifecycle ingest-co-sample ingest-durham-sample require-postgres-password ingest-nc-sample ingest-nc-ie-sample ingest-ga-sample ingest-ca-sample ingest-mn-sample ingest-wa-sample ingest-tx-sample ingest-pa-sample ingest-oh-sample ingest-in-sample ingest-il-sample ingest-nj-sample ingest-va-sample ingest-sf-sample ingest-la-city-sample ingest-nyc-sample ingest-nc-past-results-2022-2024 download-ga quality-check quality-freshness entity-resolve entity-resolve-dry api-dev graph-load load-test refresh-cf-data refresh-cf-priority gate-L1 gate-L3 gate-L5 gate-L6 gate-L6-pilot gate-L7 gate-L10 gate-L14 keel-status keel-summary keel-current keel-reviews-status evidence-rotate

require-postgres-password:
	@test -n "$${POSTGRES_PASSWORD:-}" || { echo "POSTGRES_PASSWORD must be set in the environment" >&2; exit 1; }

db-up: require-postgres-password
	docker compose -f infra/docker-compose.yml up -d

db-down: require-postgres-password
	docker compose -f infra/docker-compose.yml down

db-reset: require-postgres-password
	@if command -v psql >/dev/null 2>&1; then \
		PGPASSWORD="$(POSTGRES_PASSWORD)" psql -v ON_ERROR_STOP=1 -h "$(DB_HOST)" -p "$(POSTGRES_PORT)" -U "$(POSTGRES_USER)" "$(POSTGRES_DB)" -c "DROP SCHEMA IF EXISTS cf CASCADE; DROP SCHEMA IF EXISTS prop CASCADE; DROP SCHEMA IF EXISTS civic CASCADE; DROP SCHEMA IF EXISTS civibus CASCADE; DROP EXTENSION IF EXISTS age CASCADE; DROP SCHEMA IF EXISTS core CASCADE;"; \
		for schema_file in $(DB_SQL_FILES); do \
			PGPASSWORD="$(POSTGRES_PASSWORD)" psql -v ON_ERROR_STOP=1 -h "$(DB_HOST)" -p "$(POSTGRES_PORT)" -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" -f "$$schema_file"; \
		done; \
	else \
		uv run python -c "\
import os; from pathlib import Path; import psycopg;\
files='$(DB_SQL_FILES)'.split();\
conn=psycopg.connect(user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'], dbname=os.environ['POSTGRES_DB'], host='$(DB_HOST)', port=int(os.environ['POSTGRES_PORT']), autocommit=True);\
conn.execute('DROP SCHEMA IF EXISTS cf CASCADE');\
conn.execute('DROP SCHEMA IF EXISTS prop CASCADE');\
conn.execute('DROP SCHEMA IF EXISTS civic CASCADE');\
conn.execute('DROP SCHEMA IF EXISTS civibus CASCADE');\
conn.execute('DROP EXTENSION IF EXISTS age CASCADE');\
conn.execute('DROP SCHEMA IF EXISTS core CASCADE');\
conn.autocommit=False;\
[conn.cursor().execute(Path(s).read_text(encoding='utf-8')) for s in files];\
conn.commit(); conn.close()"; \
	fi

test:
	uv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e"

test-api:
	uv run --extra dev --extra api pytest api/

test-e2e:
	uv run --extra dev pytest -m "e2e" -v

api-dev: require-postgres-password
	uv run --extra dev --extra api uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

load-test:
	uv run --extra load locust -f tests/load/locustfile.py --headless -u 5 -r 1 -t 30s

check-retired-symbols:
	@set -eu; \
	for symbol in $(RETIRED_SYMBOLS); do \
		matches="$$(git grep -nw "$$symbol" -- . $(foreach path,$(RETIRED_ALLOWLIST),":(exclude)$(path)") || true)"; \
		if [ -n "$$matches" ]; then \
			echo "retired symbol '$$symbol' has non-allowlisted references:" >&2; \
			echo "$$matches" >&2; \
			exit 1; \
		fi; \
	done

lint:
	$(MAKE) check-retired-symbols
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

validate-configs:
	uv run python -m domains.campaign_finance.validate_configs

validate-registry:
	uv run python -m domains.campaign_finance.coverage.validate_registry

render-coverage-views:
	uv run python -m domains.campaign_finance.coverage.render_summary
	uv run python -m domains.campaign_finance.coverage.lifecycle

render-region-lifecycle:
	uv run python -m domains.campaign_finance.coverage.lifecycle

ingest-fec-sample:
	uv run python -m domains.campaign_finance.ingest.cli --state NC --cycle 2024 --limit 10


ingest-fec-bulk-sample:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle 2024 --all --directory tests/fixtures/bulk --batch-size 1000

ingest-fec-ie-sample:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle 2024 --file-type schedule_e --path tests/fixtures/bulk/schedule_e_sample.csv --batch-size 1000

download-fec-bulk:
	@mkdir -p "$(FEC_BULK_DIR)"
	@set -e; urls="$$(FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)" uv run python -c 'from domains.campaign_finance.ingest.bulk_cli import fec_baseline_urls; import os; [print(url) for url in fec_baseline_urls(int(os.environ["FEC_BULK_CYCLE"])).values()]')" || exit $$?; \
	for url in $$urls; do \
		archive="$$(basename "$$url")"; \
		curl -fLsS -z "$(FEC_BULK_DIR)/$$archive" -o "$(FEC_BULK_DIR)/$$archive" "$$url"; \
	done

download-fec-schedule-e:
	@mkdir -p "$(FEC_BULK_DIR)"
	@set -e; url="$$(FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)" uv run python -c 'from domains.campaign_finance.ingest.bulk_cli import fec_schedule_e_url; import os; print(fec_schedule_e_url(int(os.environ["FEC_BULK_CYCLE"])))')" || exit $$?; \
	archive="$$(basename "$$url")"; \
	curl -fLsS -z "$(FEC_BULK_DIR)/$$archive" -o "$(FEC_BULK_DIR)/$$archive" "$$url"

ingest-fec-bulk:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle $(FEC_BULK_CYCLE) --all --directory $(FEC_BULK_DIR) --batch-size 1000

ingest-fec-schedule-e:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle $(FEC_BULK_CYCLE) --file-type schedule_e --path $(FEC_BULK_DIR)/independent_expenditure_$(FEC_BULK_CYCLE).csv --batch-size 1000

download-irs-527:
	uv run python -m domains.campaign_finance.ingest.dark_money.cli download --dest-dir $(IRS_527_DATA_DIR)

ingest-irs-527-sample:
	uv run python -m domains.campaign_finance.ingest.dark_money.cli ingest --path tests/fixtures/bulk/irs_527_sample.zip --limit 1000

ingest-irs-527:
	uv run python -m domains.campaign_finance.ingest.dark_money.cli ingest --path $(IRS_527_PATH) --batch-size $(IRS_527_BATCH_SIZE)

ingest-co-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.CO.scraper.cli --path domains/campaign_finance/jurisdictions/states/CO/scraper/test_fixtures/sample_contributions.csv --year 2024 --data-type contributions

ingest-durham-sample:
	uv run python -m domains.property.ingest.cli

ingest-nc-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli --path domains/campaign_finance/jurisdictions/states/NC/tests/fixtures/transaction_export_sample.csv --data-type transactions

ingest-nc-ie-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli --path domains/campaign_finance/jurisdictions/states/NC/tests/fixtures/cfdoclkup_ie_document_index_sample_2026_04_18.csv --data-type ie-document-index

ingest-ga-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.GA.scraper.cli --path domains/campaign_finance/jurisdictions/states/GA/tests/fixtures/contribution_export_sample.xls --data-type contributions

ingest-ca-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.CA.scraper.cli --path domains/campaign_finance/jurisdictions/states/CA/scraper/test_fixtures/sample_archive

ingest-mn-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.MN.scraper.cli --path domains/campaign_finance/jurisdictions/states/MN/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-wa-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.WA.scraper.cli --path domains/campaign_finance/jurisdictions/states/WA/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-tx-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.TX.scraper.cli --path domains/campaign_finance/jurisdictions/states/TX/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-pa-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.PA.scraper.cli --year 2025 --path domains/campaign_finance/jurisdictions/states/PA/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-oh-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.OH.scraper.cli --path domains/campaign_finance/jurisdictions/states/OH/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-in-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.IN.scraper.cli --path domains/campaign_finance/jurisdictions/states/IN/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-il-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.IL.scraper.cli --path domains/campaign_finance/jurisdictions/states/IL/scraper/test_fixtures/Receipts_sample.txt --data-type contributions

ingest-nj-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.NJ.scraper.cli --path domains/campaign_finance/jurisdictions/states/NJ/scraper/test_fixtures/sample_contributions.csv --data-type contributions

ingest-va-sample:
	uv run python -m domains.campaign_finance.jurisdictions.states.VA.scraper.cli --path domains/campaign_finance/jurisdictions/states/VA/scraper/test_fixtures/sample_contributions.csv --data-type contributions --dry-run

ingest-sf-sample:
	uv run python -m domains.campaign_finance.jurisdictions.cities.SF.scraper.cli --path domains/campaign_finance/jurisdictions/cities/SF/tests/test_fixtures/sample_transactions.csv --data-type transactions

ingest-la-city-sample:
	uv run python -m domains.campaign_finance.jurisdictions.cities.LA.scraper.cli --path domains/campaign_finance/jurisdictions/cities/LA/tests/test_fixtures/sample_transactions.csv --data-type transactions

ingest-nyc-sample:
	uv run python -m domains.campaign_finance.jurisdictions.cities.NYC.scraper.cli --path domains/campaign_finance/jurisdictions/cities/NYC/tests/test_fixtures/sample_transactions.csv --data-type transactions --dry-run

download-ga:
	uv run --extra download python -m domains.campaign_finance.jurisdictions.states.GA.scraper.cli --download --data-type contributions --candidate "Kemp" --date-start "01/01/2024" --date-end "01/31/2024" --dry-run

quality-check:
	uv run python -m domains.campaign_finance.quality.cli $(QUALITY_CHECK_ARGS)
	uv run python -m domains.campaign_finance.coverage.validate_registry

quality-freshness:
	uv run python -m domains.campaign_finance.quality.cli --check freshness $(QUALITY_FRESHNESS_ARGS)

entity-resolve: require-postgres-password
	uv run --extra entity-resolution python -m core.entity_resolution.cli --entity-type person --action run

entity-resolve-dry: require-postgres-password
	uv run --extra entity-resolution python -m core.entity_resolution.cli --entity-type person --action run --dry-run

graph-load: require-postgres-password
	uv run python -m core.graph.cli

refresh-cf-data:
	uv run python -m core.refresh.runner --scope all $(REFRESH_CF_ARGS)

refresh-cf-priority:
	uv run python -m core.refresh.runner --scope priority $(REFRESH_CF_ARGS)

ingest-nc-past-results-2022-2024:
	uv run python -m core.refresh.runner --scope all --job-key-prefix civics-nc-past-results-2022-2024 $(REFRESH_CF_ARGS)

gate-L1:
	uv run python -m core.keel_gate_l1 --jurisdiction $(JURISDICTION)

gate-L3:
	uv run python -m core.keel_gate_l3 --jurisdiction $(JURISDICTION)

gate-L5:
	uv run python -m core.refresh.gate_l5

gate-L6:
	uv run python -m core.keel_gate_l6 --jurisdiction $(JURISDICTION) --data-type $(DATA_TYPE) --path $(FILE_PATH) --load-id $(LOAD_ID)

gate-L6-pilot:
	uv run python -m core.keel_gate_l6 --jurisdiction NC --pilot-fixture-suite

gate-L7:
	uv run python -m core.keel_gate_l7

gate-L10:
	uv run python -m core.keel_gate_l10 --scope $(JURISDICTION)

gate-L14:
	uv run python -m core.keel_gate_l14

keel-status:
	uv run python -m core.keel_status

keel-summary:
	uv run python -m core.keel_status --summary

keel-current:
	uv run python -m core.keel_current

keel-reviews-status:
	uv run python -m core.keel_review_schedule

evidence-rotate:
	uv run python -m core.keel_evidence_retention $(ROTATE_FLAGS)
