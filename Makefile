POSTGRES_USER ?= civibus
POSTGRES_DB ?= civibus
POSTGRES_PORT ?= 5433
POSTGRES_PORT_ORIGIN := $(origin POSTGRES_PORT)
POSTGRES_PORT_CALLER_SUPPLIED := $(if $(filter environment command line,$(POSTGRES_PORT_ORIGIN)),1)
# Freeze caller values without recursively expanding embedded Make syntax. These
# values also enter shell recipes, where they must be read from the environment.
override POSTGRES_PORT := $(value POSTGRES_PORT)
WORKSPACE_SLUG := $(shell basename "$$(dirname "$(CURDIR)")" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_$$//')
COMPOSE_PROJECT_NAME_ORIGIN := $(origin COMPOSE_PROJECT_NAME)
COMPOSE_PROJECT_NAME ?= civibus_$(WORKSPACE_SLUG)
ifneq ($(filter environment command line,$(COMPOSE_PROJECT_NAME_ORIGIN)),)
override COMPOSE_PROJECT_NAME := $(value COMPOSE_PROJECT_NAME)
else
override COMPOSE_PROJECT_NAME := civibus_$(WORKSPACE_SLUG)
endif

export POSTGRES_USER
export POSTGRES_PASSWORD
export POSTGRES_DB
export POSTGRES_PORT
export COMPOSE_PROJECT_NAME

DB_HOST := localhost
# Keep the schema reset manifest repo-owned: db-reset interpolates this list into
# shell and Python recipe bodies, so command-line overrides would become code execution.
override DB_SQL_FILES := core/schema/entities.sql core/schema/migrations/2026_04_30_person_bio_fields.sql core/schema/jurisdiction.sql core/schema/provenance.sql core/schema/entity_resolution.sql core/schema/er_views.sql domains/campaign_finance/schema/tables.sql domains/campaign_finance/schema/nc_orchestrator_tables.sql domains/campaign_finance/schema/dark_money_tables.sql domains/property/schema/tables.sql domains/civics/schema/tables.sql infra/db/09-age-graph-bootstrap.sql
FEC_BULK_CYCLE ?= 2024
FEC_BULK_DIR ?= data/fec/bulk/$(FEC_BULK_CYCLE)
IRS_527_DATA_DIR ?= data/irs_527
IRS_527_PATH ?= $(IRS_527_DATA_DIR)/FullDataFile.txt
IRS_527_BATCH_SIZE ?= 1000
REFRESH_CF_ARGS ?= --dry-run
# Federal-first v1: quality sweeps default to the active FEC jurisdiction so
# parked state/city sources (frozen, often stale in dev DBs) don't add noise.
# Use `make quality-check-all` / override the vars to sweep everything.
QUALITY_CHECK_ARGS ?= --jurisdiction federal/fec
QUALITY_FRESHNESS_ARGS ?= --jurisdiction federal/fec
RETIRED_SYMBOLS := INDIANA_FRESHNESS_NOTE _CASE_FIXTURE_SOURCES _PILOT_SUPPORTED_STATES is_autopublish_enabled
RETIRED_ALLOWLIST := \
	core/keel_gate_l11.py \
	tests/keel/test_gate_l15.py \
	docs/reference/keel/** \
	chats/** \
	.matt/projects/** \
	Makefile

MERGE_DB_BACKED_TEST_NODES := \
	core/test_refresh_runner.py::test_masters_with_spine_skipped_preserves_officeholder_money_coverage \
	tests/integration/test_donor_search_query_contract.py::test_search_donors_full_scope_bound_preserves_high_volume_donor_values
QA_FAST_STRUCTURAL_TEST_PATHS := \
	tests/ci \
	tests/test_beads_adoption_contract.py
QA_FAST_STRUCTURAL_MARKER_EXPRESSION := not integration and not e2e and not projected_public_contract
QA_FAST_PRODUCT_TEST_PATHS := \
	api/ \
	core/people/enrichment \
	core/entity_resolution \
	domains/campaign_finance/entity_extractors \
	domains/campaign_finance/normalize \
	domains/campaign_finance/tests \
	domains/civics/loaders/test_federal_fec_races.py \
	tests/test_stage1_fec_committee_summary_format_outputs.py \
	tests/test_stage1_fec_schedule_b_source_contract.py \
	tests/test_stage1_fec_schedule_e_format_outputs.py \
	tests/test_schedule_e_test_support.py
QA_FAST_PRODUCT_MARKER_EXPRESSION := not integration and not e2e and not projected_public_contract and not dev_repo_only


.PHONY: db-up db-wait db-down db-teardown db-reset test qa-fast qa-fast-public coverage-public test-public test-projected-public-contract test-api test-e2e lint check-retired-symbols ingest-fec-sample ingest-fec-bulk-sample ingest-fec-bulk ingest-fec-federal ingest-fec-ie-sample download-fec-bulk download-fec-weball download-fec-schedule-e download-fec-committee-summary ingest-fec-schedule-e download-irs-527 ingest-irs-527-sample ingest-irs-527 validate-configs validate-registry render-coverage-views render-region-lifecycle ingest-co-sample ingest-durham-sample require-postgres-password ingest-nc-sample ingest-nc-ie-sample ingest-ga-sample ingest-ca-sample ingest-mn-sample ingest-wa-sample ingest-tx-sample ingest-pa-sample ingest-oh-sample ingest-in-sample ingest-il-sample ingest-nj-sample ingest-va-sample ingest-sf-sample ingest-la-city-sample ingest-nyc-sample ingest-nc-past-results-2022-2024 download-ga quality-check quality-freshness entity-resolve entity-resolve-dry api-dev graph-load load-test refresh-cf-data refresh-cf-priority gate-L1 gate-L3 gate-L5 gate-L6 gate-L6-pilot gate-L7 gate-L10 gate-L14 keel-status keel-summary keel-current keel-reviews-status evidence-rotate

require-postgres-password:
	@test -n "$${POSTGRES_PASSWORD:-}" || { echo "POSTGRES_PASSWORD must be set in the environment" >&2; exit 1; }

# Port 5475 is reserved for qa-integration, which pins it below and
# refuses to run when the port is already bound. A lane database started on 5475
# under any other COMPOSE_PROJECT_NAME therefore disables the DB-backed
# merged-union gate for every concurrent worker on this host, and the symptom
# surfaces at merge time as "Port 5475 is already bound by a likely concurrent
# integration run" rather than at the point of the mistake. Observed 2026-08-01:
# civibus_l13-db-1 held 127.0.0.1:5475 while its batch's own integration gate was
# still owed. Batch port allocations are prose; this is the enforcement.
INTEGRATION_RESERVED_PORT := 5475
INTEGRATION_RESERVED_PROJECT := civibus_integration_local

.PHONY: reject-reserved-integration-port reject-unallocated-lane-port
reject-reserved-integration-port:
	@port="$${POSTGRES_PORT}"; \
	case "$$port" in \
		''|0*|*[!0-9]*|??????*) \
			printf 'POSTGRES_PORT=%s must be a canonical decimal port from 1 through 65535\n' "$$port" >&2; \
			exit 1 ;; \
	esac; \
	if [ "$$port" -gt 65535 ]; then \
		printf 'POSTGRES_PORT=%s must be a canonical decimal port from 1 through 65535\n' "$$port" >&2; \
		exit 1; \
	fi; \
	if [ "$$port" = "$(INTEGRATION_RESERVED_PORT)" ] && \
		[ "$${COMPOSE_PROJECT_NAME}" != "$(INTEGRATION_RESERVED_PROJECT)" ]; then \
		printf '%s\n' "POSTGRES_PORT=$(INTEGRATION_RESERVED_PORT) is reserved for qa-integration; COMPOSE_PROJECT_NAME=$${COMPOSE_PROJECT_NAME} may not bind it. Use the port your batch allocated." >&2; \
		exit 1; \
	fi

reject-unallocated-lane-port:
	@if [ -z "$(POSTGRES_PORT_CALLER_SUPPLIED)" ] || [ -z "$${POSTGRES_PORT}" ]; then \
		printf '%s\n' "A non-empty POSTGRES_PORT must be supplied by environment or command line for COMPOSE_PROJECT_NAME=$${COMPOSE_PROJECT_NAME}; implicit default POSTGRES_PORT=$${POSTGRES_PORT} is not an allocated lane port." >&2; \
		exit 1; \
	fi

db-up: require-postgres-password reject-reserved-integration-port reject-unallocated-lane-port
	docker compose -f infra/docker-compose.yml up -d

# Blocks until the compose-owned db container reports healthy. One owner for
# every workflow that seeds after db-up; integration.yml predates this target
# and keeps its own pinned inline copy by contract.
db-wait: require-postgres-password reject-unallocated-lane-port
	@container_id="$$(docker compose -f infra/docker-compose.yml ps -q db)"; \
	if [ -z "$$container_id" ]; then \
		echo "Database container ID not found" >&2; \
		exit 1; \
	fi; \
	for attempt in $$(seq 1 60); do \
		status="$$(docker inspect -f '{{.State.Health.Status}}' "$$container_id" 2>/dev/null || true)"; \
		if [ "$$status" = "healthy" ]; then \
			exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "Database did not become healthy in time" >&2; \
	exit 1

db-down: require-postgres-password reject-unallocated-lane-port
	docker compose -f infra/docker-compose.yml down

# Destructive counterpart to db-down: db-down leaves the lane volume in place,
# so honest per-lane cleanup needs an explicit path that removes the volume and
# removes orphaned services in the same Compose project, then proves the
# compose-owned volume `$(COMPOSE_PROJECT_NAME)_civibus_db_data` is actually
# gone. The check is anchored and literal (grep -Fqx) so civibus_c1 cannot false-match
# civibus_c10.
db-teardown: require-postgres-password reject-unallocated-lane-port
	docker compose -f infra/docker-compose.yml down --volumes --remove-orphans
	@volume_names="$$(docker volume ls --format '{{.Name}}')"; volume_ls_status=$$?; \
	if [ "$$volume_ls_status" -ne 0 ]; then \
		echo "TEARDOWN FAILED: unable to inspect Docker volumes" >&2; \
		exit "$$volume_ls_status"; \
	fi; \
	if printf '%s\n' "$$volume_names" | grep -Fqx "$${COMPOSE_PROJECT_NAME}_civibus_db_data"; then \
		printf 'TEARDOWN FAILED: %s volume survives\n' "$${COMPOSE_PROJECT_NAME}" >&2; \
		exit 1; \
	fi; \
	printf 'TEARDOWN CLEAN: docker volume ls contains no %s volume\n' "$${COMPOSE_PROJECT_NAME}"

db-reset: require-postgres-password reject-reserved-integration-port reject-unallocated-lane-port
	@set -e; if command -v psql >/dev/null 2>&1; then \
		for attempt in $$(seq 1 60); do \
			if PGPASSWORD="$(POSTGRES_PASSWORD)" psql -v ON_ERROR_STOP=1 -h "$(DB_HOST)" -p "$(POSTGRES_PORT)" -U "$(POSTGRES_USER)" "$(POSTGRES_DB)" -c "SELECT 1" >/dev/null 2>&1; then \
				break; \
			fi; \
			if [ "$$attempt" -eq 60 ]; then \
				echo "PostgreSQL did not become ready for db-reset" >&2; \
				exit 1; \
			fi; \
			sleep 1; \
		done; \
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

# The merge-slice preflight delegates to conftest.merge_db_slice_probe() rather
# than connecting itself. A hand-rolled `get_connection()` one-shot here got the
# shadow/run decision wrong: it skipped the password default and startup retries
# the DB-backed nodes get from the root conftest, so with POSTGRES_PASSWORD unset
# it printed the shadow warning against a database the tests could have reached.
# The probe also echoes the target core.db actually resolved, which is not
# necessarily this Makefile's DB_HOST. Only its canonical-unavailability status
# takes the shadow branch; unexpected probe failures remain fatal.
test:
	uv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not projected_public_contract"
	@merge_db_target="$$(uv run --extra dev --extra entity-resolution python -c 'import conftest; conftest.merge_db_slice_probe()')"; \
	merge_db_probe_status=$$?; \
	if [ "$$merge_db_probe_status" -eq 0 ]; then \
		CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest $(MERGE_DB_BACKED_TEST_NODES); \
	elif [ "$$merge_db_probe_status" -eq 1 ]; then \
		printf '%s\n' "CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN $$merge_db_target nodes=$(MERGE_DB_BACKED_TEST_NODES)"; \
	else \
		exit "$$merge_db_probe_status"; \
	fi

# Baseline sections 5/8: web test is 5.3-6.1s, check is 3.9s, and a warm install is 2.0s.
# This tier retains web/node_modules while web test caches may be warm or clean; the former broad
# candidate's 218.4s p50/219.4s p95 exceeded 120s in Python, so the inexpensive web check stays.
qa-fast:
	@test -d web/node_modules || { printf '%s\n' 'qa-fast requires web/node_modules; run npm --prefix web ci' >&2; exit 1; }
	$(MAKE) lint
	npm --prefix web test
	npm --prefix web run check
	uv run --extra dev --extra entity-resolution pytest $(QA_FAST_STRUCTURAL_TEST_PATHS) -m "$(QA_FAST_STRUCTURAL_MARKER_EXPRESSION)"
	uv run --extra dev --extra entity-resolution pytest $(QA_FAST_PRODUCT_TEST_PATHS) -m "$(QA_FAST_PRODUCT_MARKER_EXPRESSION)"

# qa-fast viewed from the public mirror: identical composition, with
# dev_repo_only nodes deselected because their private assets (.beads/, the
# frozen ROADMAP.md, dev-host CLIs) are intentionally absent there. The product
# expression already excludes dev_repo_only in both localities, so only the
# structural expression needs the append. No recipe lines here on purpose —
# any would fork the composition away from its single qa-fast owner.
qa-fast-public: QA_FAST_STRUCTURAL_MARKER_EXPRESSION += and not dev_repo_only
qa-fast-public: qa-fast

# Nightly-owned coverage over the public unit selection. Kept in the Makefile
# so workflows invoke it by name instead of inlining pytest flags that drift.
coverage-public:
	uv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not dev_repo_only" --cov=api --cov=core --cov=domains --cov-fail-under=70

test-public:
	uv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not dev_repo_only"

test-projected-public-contract:
	uv run --extra dev --extra entity-resolution pytest -m "projected_public_contract" tests/test_debbie_projected_public_contract.py::test_projected_current_public_unit_selection_failures_are_classified

# .github/workflows/integration.yml is the source of truth for the product
# selection; change this local lifecycle owner whenever that suite changes.
.PHONY: qa-integration test-integration-local
qa-integration: override POSTGRES_PORT := 5475
qa-integration: override COMPOSE_PROJECT_NAME := civibus_integration_local
qa-integration:
	@set -eu; \
	if [ -n "$(POSTGRES_PORT_CALLER_SUPPLIED)" ]; then \
		echo "qa-integration pins POSTGRES_PORT=5475 internally; do not provide a POSTGRES_PORT override" >&2; \
		exit 1; \
	fi; \
	if ! POSTGRES_PORT=5475 python3 -c 'import os, socket; probe = socket.socket(); probe.bind(("127.0.0.1", int(os.environ["POSTGRES_PORT"])))'; then \
		echo "Port 5475 is already bound by a likely concurrent integration run; wait for it to finish, then retry" >&2; \
		exit 1; \
	fi; \
	docker info >/dev/null 2>&1 || { echo "qa-integration requires Docker-backed PostgreSQL, but the Docker daemon is unavailable" >&2; exit 1; }; \
	cleanup_required=0; \
	cleanup() { \
		target_status=$$?; \
		trap - EXIT; \
		if [ "$$cleanup_required" -eq 1 ]; then \
			docker compose -f infra/docker-compose.yml down --volumes --remove-orphans || target_status=$$?; \
		fi; \
		exit "$$target_status"; \
	}; \
	trap cleanup EXIT; \
	trap 'exit 129' HUP; \
	trap 'exit 130' INT; \
	trap 'exit 143' TERM; \
	cleanup_required=1; \
	docker compose -f infra/docker-compose.yml down --volumes --remove-orphans; \
	$(MAKE) db-up; \
	container_id="$$(docker compose -f infra/docker-compose.yml ps -q db)"; \
	if [ -z "$$container_id" ]; then \
		echo "Database container ID not found" >&2; \
		exit 1; \
	fi; \
	for attempt in $$(seq 1 60); do \
		status="$$(docker inspect -f '{{.State.Health.Status}}' "$$container_id" 2>/dev/null || true)"; \
		if [ "$$status" = "healthy" ]; then \
			break; \
		fi; \
		if [ "$$attempt" -eq 60 ]; then \
			echo "Database did not become healthy in time" >&2; \
			exit 1; \
		fi; \
		sleep 2; \
	done; \
	$(MAKE) db-reset; \
	$(MAKE) ingest-fec-bulk-sample; \
	$(MAKE) graph-load; \
	CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest -m "integration and not quarantined" \
		api/ \
		core/ \
		domains/ \
		tests/integration/ \
		tests/e2e/ \
		tests/test_db_integration.py \
		tests/test_graph_queries.py \
		tests/test_relational_queries.py; \
	CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest $(MERGE_DB_BACKED_TEST_NODES)

test-integration-local: qa-integration

# Parked state/city pipeline suite (frozen for federal-first v1; excluded from
# `make test` and CI by the conftest.py quarantine). Run before touching shared
# loader surfaces (jurisdictions/states/load_utils.py, core/refresh/job_builders.py)
# or when un-parking a jurisdiction post-v1.
# Declared .PHONY on its own line to avoid textual conflicts on the shared list.
.PHONY: test-parked
test-parked:
	CIVIBUS_INCLUDE_PARKED=1 uv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e" \
		domains/campaign_finance/jurisdictions/states domains/campaign_finance/jurisdictions/cities

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
	@if [ -f scripts/lane_authoring_hazard_checker.py ]; then uv run python scripts/lane_authoring_hazard_checker.py; fi

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

download-fec-committee-summary:
	@mkdir -p "$(FEC_BULK_DIR)"
	@set -e; url="$$(FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)" uv run python -c 'from domains.campaign_finance.ingest.bulk_cli import fec_committee_summary_url; import os; print(fec_committee_summary_url(int(os.environ["FEC_BULK_CYCLE"])))')" || exit $$?; \
	archive="$$(basename "$$url")"; \
	curl -fLsS -z "$(FEC_BULK_DIR)/$$archive" -o "$(FEC_BULK_DIR)/$$archive" "$$url"

download-fec-weball:
	@mkdir -p "$(FEC_BULK_DIR)"
	@set -e; url="$$(FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)" uv run python -c 'from domains.campaign_finance.ingest.bulk_cli import fec_weball_url; import os; print(fec_weball_url(int(os.environ["FEC_BULK_CYCLE"])))')" || exit $$?; \
	archive="$$(basename "$$url")"; \
	curl -fLsS -z "$(FEC_BULK_DIR)/$$archive" -o "$(FEC_BULK_DIR)/$$archive" "$$url"

ingest-fec-bulk:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle $(FEC_BULK_CYCLE) --all --directory $(FEC_BULK_DIR) --batch-size 1000

ingest-fec-federal:
	uv run python -m domains.campaign_finance.ingest.bulk_cli --cycle $(FEC_BULK_CYCLE) --federal --directory $(FEC_BULK_DIR) --batch-size 1000

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

# Unscoped sweep across every jurisdiction present in the DB (incl. parked).
.PHONY: quality-check-all
quality-check-all:
	uv run python -m domains.campaign_finance.quality.cli
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
