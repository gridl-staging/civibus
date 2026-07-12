-- Stage 2 Campaign Finance Schema
--
-- Migration order
-- 1) Load core:
--    - core/schema/entities.sql
--    - core/schema/provenance.sql
-- 2) Load this file:
--    - domains/campaign_finance/schema/tables.sql
--
-- Schema ownership
-- This file owns exactly nine tables:
--   - cf.committee
--   - cf.committee_summary
--   - cf.stage4_resume_checkpoint
--   - cf.candidate
--   - cf.election
--   - cf.filing
--   - cf.transaction
--   - cf.candidate_committee_link
--   - cf.nc_committee_registry
--
-- Shared conventions for this stage
--   - UUID primary keys use uuid_generate_v4().
--   - updated_at columns are maintained via core.set_updated_at().
--   - NULLability reflects ingestion reality:
--       - Optional core entity links are nullable until resolution runs.
--       - Temporal columns are nullable when source data is incomplete.
--   - Stable IDs and normalized lookups use indexed natural keys:
--       - Committee and candidate IDs from FEC (CMTE_ID, CAND_ID).
--       - Filings and transactions support filing-level and memo/amendment checks.
--   - Temporal relationships should prefer daterange + core.date_precision where both
--     bounds are meaningful (candidate_committee_link uses this stage-wide standard).
--   - Filing timeliness rule (canonical):
--       days_late = max(0, receipt_date - due_date) when both dates are present.

CREATE SCHEMA IF NOT EXISTS cf;

CREATE TABLE cf.committee (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fec_committee_id  TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    organization_id  UUID REFERENCES core.organization(id),
    committee_type   TEXT,
    committee_designation TEXT,
    party            TEXT,
    state            TEXT,
    city             TEXT,
    zip_code         TEXT,
    treasurer_name   TEXT,
    source_record_id UUID REFERENCES core.source_record(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_committee_fec_fec_id_format
        CHECK (fec_committee_id ~ '^C[0-9]{8}$'),
    CONSTRAINT ck_committee_state_len
        CHECK (state IS NULL OR char_length(state) = 2)
);

-- fec_committee_id already has an implicit index from UNIQUE constraint
CREATE INDEX idx_committee_name_trgm ON cf.committee USING GIN (name gin_trgm_ops);
CREATE INDEX idx_committee_state ON cf.committee (state);
CREATE INDEX idx_committee_type ON cf.committee (committee_type);
CREATE INDEX idx_committee_designation ON cf.committee (committee_designation);
CREATE INDEX idx_committee_party ON cf.committee (party);
CREATE INDEX idx_committee_org ON cf.committee (organization_id)
    WHERE organization_id IS NOT NULL;
CREATE INDEX idx_committee_source_record_id ON cf.committee (source_record_id);

CREATE TABLE cf.committee_summary (
    id                                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    committee_id                            UUID NOT NULL REFERENCES cf.committee(id),
    cycle                                   INTEGER NOT NULL,
    link_image                              TEXT,
    committee_name                          TEXT,
    committee_type                          TEXT,
    committee_designation                   TEXT,
    committee_filing_frequency              TEXT,
    committee_street_1                      TEXT,
    committee_street_2                      TEXT,
    committee_city                          TEXT,
    committee_state                         TEXT,
    committee_zip                           TEXT,
    treasurer_name                          TEXT,
    individual_contributions                NUMERIC(14,2),
    party_committee_contributions           NUMERIC(14,2),
    other_committee_contributions           NUMERIC(14,2),
    total_contributions                     NUMERIC(14,2),
    transfers_from_other_authorized_committees NUMERIC(14,2),
    offsets_to_operating_expenditures       NUMERIC(14,2),
    other_receipts                          NUMERIC(14,2),
    total_receipts                          NUMERIC(14,2),
    transfers_to_other_authorized_committees NUMERIC(14,2),
    other_loan_repayments                   NUMERIC(14,2),
    individual_refunds                      NUMERIC(14,2),
    political_party_committee_refunds       NUMERIC(14,2),
    total_contribution_refunds              NUMERIC(14,2),
    other_disbursements                     NUMERIC(14,2),
    total_disbursements                     NUMERIC(14,2),
    net_contributions                       NUMERIC(14,2),
    net_operating_expenditures              NUMERIC(14,2),
    cash_on_hand_beginning_of_period        NUMERIC(14,2),
    coverage_start_date                     DATE,
    cash_on_hand                            NUMERIC(14,2),
    coverage_end_date                       DATE,
    debts_owed_by_committee                 NUMERIC(14,2),
    debts_owed_to_committee                 NUMERIC(14,2),
    individual_itemized_contributions       NUMERIC(14,2),
    individual_unitemized_contributions     NUMERIC(14,2),
    other_loans                             NUMERIC(14,2),
    transfers_from_nonfederal_account       NUMERIC(14,2),
    transfers_from_nonfederal_levin         NUMERIC(14,2),
    total_nonfederal_transfers              NUMERIC(14,2),
    loan_repayments_received                NUMERIC(14,2),
    offsets_to_fundraising                  NUMERIC(14,2),
    offsets_to_legal_accounting             NUMERIC(14,2),
    federal_candidate_contribution_refunds  NUMERIC(14,2),
    total_federal_receipts                  NUMERIC(14,2),
    shared_federal_operating_expenditures   NUMERIC(14,2),
    shared_nonfederal_operating_expenditures NUMERIC(14,2),
    other_federal_operating_expenditures    NUMERIC(14,2),
    total_operating_expenditures            NUMERIC(14,2),
    federal_candidate_committee_contributions NUMERIC(14,2),
    independent_expenditures                NUMERIC(14,2),
    coordinated_expenditures_by_party_committee NUMERIC(14,2),
    loans_made                              NUMERIC(14,2),
    shared_federal_activity_federal_share   NUMERIC(14,2),
    shared_federal_activity_nonfederal      NUMERIC(14,2),
    nonallocated_federal_election_activity  NUMERIC(14,2),
    total_federal_election_activity         NUMERIC(14,2),
    total_federal_disbursements             NUMERIC(14,2),
    candidate_contributions                 NUMERIC(14,2),
    candidate_loans                         NUMERIC(14,2),
    total_loans                             NUMERIC(14,2),
    operating_expenditures                  NUMERIC(14,2),
    candidate_loan_repayments               NUMERIC(14,2),
    total_loan_repayments                   NUMERIC(14,2),
    other_committee_refunds                 NUMERIC(14,2),
    total_offsets_to_operating_expenditures NUMERIC(14,2),
    exempt_legal_accounting_disbursements   NUMERIC(14,2),
    fundraising_disbursements               NUMERIC(14,2),
    itemized_refunds_rebates_returns        NUMERIC(14,2),
    subtotal_refunds_rebates_returns        NUMERIC(14,2),
    unitemized_refunds_rebates_returns      NUMERIC(14,2),
    itemized_other_refunds_rebates_returns  NUMERIC(14,2),
    unitemized_other_refunds_rebates_returns NUMERIC(14,2),
    subtotal_other_refunds_rebates_returns  NUMERIC(14,2),
    itemized_other_income                   NUMERIC(14,2),
    unitemized_other_income                 NUMERIC(14,2),
    expenditures_prior_years_subject_to_limits NUMERIC(14,2),
    expenditures_subject_to_limits          NUMERIC(14,2),
    federal_funds                           NUMERIC(14,2),
    itemized_convention_expenditures_disbursements NUMERIC(14,2),
    itemized_other_disbursements            NUMERIC(14,2),
    subtotal_convention_expenditures_disbursements NUMERIC(14,2),
    total_expenditures_subject_to_limits    NUMERIC(14,2),
    unitemized_convention_expenditures_disbursements NUMERIC(14,2),
    unitemized_other_disbursements          NUMERIC(14,2),
    total_communication_cost                NUMERIC(14,2),
    cash_on_hand_beginning_of_year          NUMERIC(14,2),
    cash_on_hand_close_of_year              NUMERIC(14,2),
    source_record_id                        UUID REFERENCES core.source_record(id),
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_committee_summary_coverage_order
        CHECK (coverage_start_date IS NULL OR coverage_end_date IS NULL OR coverage_start_date <= coverage_end_date)
);

CREATE UNIQUE INDEX uq_committee_summary_committee_cycle
    ON cf.committee_summary (committee_id, cycle);
CREATE INDEX idx_committee_summary_committee_id
    ON cf.committee_summary (committee_id);
CREATE INDEX idx_committee_summary_cycle
    ON cf.committee_summary (cycle);
CREATE INDEX idx_committee_summary_source_record_id
    ON cf.committee_summary (source_record_id);

CREATE TABLE cf.stage4_resume_checkpoint (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id         UUID NOT NULL REFERENCES core.data_source(id),
    cycle                  INTEGER NOT NULL,
    file_type              TEXT NOT NULL,
    archive_fingerprint    TEXT NOT NULL,
    archive_member_name    TEXT,
    next_source_row_number BIGINT NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_stage4_resume_checkpoint_file_type
        CHECK (file_type IN ('itcont')),
    CONSTRAINT ck_stage4_resume_checkpoint_cycle
        CHECK (cycle >= 1900),
    CONSTRAINT ck_stage4_resume_checkpoint_next_source_row_number
        CHECK (next_source_row_number >= 0)
);

CREATE UNIQUE INDEX uq_stage4_resume_checkpoint_identity
    ON cf.stage4_resume_checkpoint (data_source_id, cycle, file_type);
CREATE INDEX idx_stage4_resume_checkpoint_data_source_id
    ON cf.stage4_resume_checkpoint (data_source_id);
CREATE INDEX idx_stage4_resume_checkpoint_updated_at
    ON cf.stage4_resume_checkpoint (updated_at);

CREATE TABLE cf.candidate (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fec_candidate_id         TEXT NOT NULL UNIQUE,
    name                     TEXT NOT NULL,
    person_id                UUID REFERENCES core.person(id),
    party                    TEXT,
    office                   TEXT NOT NULL,
    state                    TEXT,
    district                 TEXT,
    incumbent_challenge      TEXT,
    principal_committee_id    UUID REFERENCES cf.committee(id),
    total_receipts           NUMERIC(14,2),
    total_disbursements      NUMERIC(14,2),
    cash_on_hand             NUMERIC(14,2),
    summary_coverage_end_date DATE,
    source_record_id         UUID REFERENCES core.source_record(id),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_candidate_office
        CHECK (office IN ('H', 'S', 'P')),
    CONSTRAINT ck_candidate_state_len
        CHECK (state IS NULL OR char_length(state) = 2),
    CONSTRAINT ck_candidate_district_len
        CHECK (district IS NULL OR char_length(district) = 2),
    CONSTRAINT ck_candidate_incumbent_challenge
        CHECK (incumbent_challenge IS NULL OR incumbent_challenge IN ('I', 'C', 'O')),
    CONSTRAINT ck_candidate_fec_candidate_id_format
        CHECK (fec_candidate_id ~ '^[HSP][0-9][A-Z0-9]{2}[0-9]{5}$')
);

-- fec_candidate_id already has an implicit index from UNIQUE constraint
CREATE INDEX idx_candidate_office_filter ON cf.candidate (office, state, district);
CREATE INDEX idx_candidate_party_filter ON cf.candidate (party);
CREATE INDEX idx_candidate_principal_committee ON cf.candidate (principal_committee_id);
CREATE INDEX idx_candidate_source_record_id ON cf.candidate (source_record_id);

CREATE TABLE cf.election (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    office                 TEXT NOT NULL,
    jurisdiction_type      TEXT NOT NULL CHECK (jurisdiction_type IN ('federal', 'state', 'other')),
    jurisdiction_code      TEXT NOT NULL,
    district               TEXT,
    candidate_election_year SMALLINT,
    fec_election_year      SMALLINT,
    valid_period           daterange NOT NULL DEFAULT daterange(NULL, NULL, '[]'::text),
    date_precision         core.date_precision NOT NULL DEFAULT 'year',
    source_record_id       UUID REFERENCES core.source_record(id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_election_office
        CHECK (office IN ('H', 'S', 'P')),
    CONSTRAINT ck_election_year
        CHECK (
            candidate_election_year IS NULL
            OR candidate_election_year >= 1900
        ),
    CONSTRAINT ck_election_valid_period
        CHECK (NOT isempty(valid_period))
);

CREATE UNIQUE INDEX uq_election_canonical_key
    ON cf.election (
        office,
        jurisdiction_type,
        jurisdiction_code,
        (district IS NULL),
        COALESCE(district, ''),
        (candidate_election_year IS NULL),
        COALESCE(candidate_election_year, 0),
        (fec_election_year IS NULL),
        COALESCE(fec_election_year, 0)
    );
CREATE INDEX idx_election_lookup
    ON cf.election (office, jurisdiction_code, candidate_election_year);
CREATE INDEX idx_election_source_record_id ON cf.election (source_record_id);

CREATE TABLE cf.filing (
    id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filing_fec_id             TEXT NOT NULL UNIQUE,
    committee_id              UUID NOT NULL REFERENCES cf.committee(id),
    candidate_id              UUID REFERENCES cf.candidate(id),
    election_id               UUID REFERENCES cf.election(id),
    report_type               TEXT,
    amendment_indicator       TEXT NOT NULL,
    filing_name               TEXT,
    coverage_start_date       DATE,
    coverage_end_date         DATE,
    due_date                  DATE,
    receipt_date              DATE,
    accepted_date             DATE,
    is_amended                BOOLEAN GENERATED ALWAYS AS (amendment_indicator = 'A') STORED,
    amended_from_filing_id     UUID REFERENCES cf.filing(id),
    source_record_id          UUID REFERENCES core.source_record(id),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    days_late                 INTEGER GENERATED ALWAYS AS (
                                CASE
                                    WHEN receipt_date IS NULL OR due_date IS NULL THEN NULL
                                    ELSE GREATEST(0, receipt_date - due_date)
                                END
                            ) STORED,

    CONSTRAINT ck_filing_amendment_indicator
        CHECK (amendment_indicator IN ('N', 'A', 'T')),
    CONSTRAINT ck_filing_coverage_order
        CHECK (coverage_start_date IS NULL OR coverage_end_date IS NULL OR coverage_start_date <= coverage_end_date),
    CONSTRAINT ck_filing_amended_parent
        CHECK (
            amended_from_filing_id IS NULL
            OR amendment_indicator IN ('A', 'T')
        )
);

CREATE INDEX idx_filing_committee_lookup ON cf.filing (committee_id);
CREATE INDEX idx_filing_candidate_lookup ON cf.filing (candidate_id) WHERE candidate_id IS NOT NULL;
CREATE INDEX idx_filing_election_lookup ON cf.filing (election_id) WHERE election_id IS NOT NULL;
CREATE INDEX idx_filing_due_date_lookup ON cf.filing (due_date);
CREATE INDEX idx_filing_receipt_date_lookup ON cf.filing (receipt_date);
CREATE INDEX idx_filing_source_record_id ON cf.filing (source_record_id)
    WHERE source_record_id IS NOT NULL;

CREATE TABLE cf.transaction (
    id                         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filing_id                  UUID NOT NULL REFERENCES cf.filing(id),
    committee_id               UUID NOT NULL REFERENCES cf.committee(id),
    transaction_type           TEXT NOT NULL,
    transaction_identifier      TEXT,
    back_ref_transaction_id    TEXT,
    sub_id                     NUMERIC(19,0),
    transaction_date           DATE,
    amount                     NUMERIC(14,2) NOT NULL,
    contributor_name_raw        TEXT,
    -- Raw FEC ENTITY_TP codes observed in Schedule A include IND, ORG, PAC, COM, CCM, CAN, PTY.
    contributor_entity_type    TEXT,
    contributor_employer        TEXT,
    contributor_occupation      TEXT,
    contributor_city           TEXT,
    contributor_state          TEXT,
    contributor_zip            TEXT,
    contributor_person_id      UUID REFERENCES core.person(id),
    contributor_organization_id UUID REFERENCES core.organization(id),
    contributor_address_id      UUID REFERENCES core.address(id),
    recipient_candidate_id     UUID REFERENCES cf.candidate(id),
    recipient_committee_id      UUID REFERENCES cf.committee(id),
    memo_code                  TEXT,
    memo_text                  TEXT,
    is_memo                    BOOLEAN NOT NULL DEFAULT FALSE,
    amendment_indicator        TEXT NOT NULL,
    amended_by_transaction_id  UUID REFERENCES cf.transaction(id),
    source_record_id           UUID REFERENCES core.source_record(id),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_is_reliable           BOOLEAN NOT NULL DEFAULT TRUE,
    support_oppose             TEXT,
    dissemination_date         DATE,
    aggregate_amount           NUMERIC(14,2),

    CONSTRAINT ck_transaction_amendment_indicator
        CHECK (amendment_indicator IN ('N', 'A', 'T')),
    CONSTRAINT ck_transaction_support_oppose
        CHECK (support_oppose IS NULL OR support_oppose IN ('S', 'O')),
    CONSTRAINT ck_transaction_contributor_id_exclusive
        CHECK (num_nonnulls(contributor_person_id, contributor_organization_id) <= 1),
    CONSTRAINT ck_transaction_contributor_state_len
        CHECK (contributor_state IS NULL OR char_length(contributor_state) = 2),
    CONSTRAINT ck_transaction_memo_flag
        CHECK (is_memo = COALESCE(memo_code IN ('X', 'x'), FALSE))
);

CREATE UNIQUE INDEX uq_transaction_sub_id
    ON cf.transaction (sub_id)
    WHERE sub_id IS NOT NULL;
CREATE UNIQUE INDEX uq_filing_transaction_identifier
    ON cf.transaction (filing_id, transaction_identifier)
    WHERE transaction_identifier IS NOT NULL;
CREATE INDEX idx_transaction_filing_lookup ON cf.transaction (filing_id);
CREATE INDEX idx_transaction_committee_date ON cf.transaction (committee_id, transaction_date);
CREATE INDEX idx_transaction_date_lookup ON cf.transaction (transaction_date);
CREATE INDEX idx_transaction_contributor_person_lookup
    ON cf.transaction (contributor_person_id)
    WHERE contributor_person_id IS NOT NULL;
CREATE INDEX idx_transaction_contributor_org_lookup
    ON cf.transaction (contributor_organization_id)
    WHERE contributor_organization_id IS NOT NULL;
CREATE INDEX idx_transaction_support_oppose
    ON cf.transaction (support_oppose)
    WHERE support_oppose IS NOT NULL;
CREATE INDEX idx_transaction_source_record_id
    ON cf.transaction (source_record_id)
    WHERE source_record_id IS NOT NULL;
-- search_donors(by=name|employer|zip) needs fuzzy text lookup on names/employers
-- and exact normalized 5-digit ZIP-prefix filtering without replacing donor ER indexes.
CREATE INDEX idx_transaction_contributor_name_lower_trgm
    ON cf.transaction USING GIN (LOWER(contributor_name_raw) gin_trgm_ops)
    WHERE contributor_name_raw IS NOT NULL;
CREATE INDEX idx_transaction_contributor_employer_lower_trgm
    ON cf.transaction USING GIN (LOWER(contributor_employer) gin_trgm_ops)
    WHERE contributor_employer IS NOT NULL;
CREATE INDEX idx_transaction_contributor_zip5
    ON cf.transaction (LEFT(contributor_zip, 5))
    WHERE contributor_zip IS NOT NULL;
-- High-frequency donor searches must intersect the mode predicate with the
-- immutable Schedule A receipt filters before row materialization. These partial
-- indexes are intentionally narrower than the general donor ER indexes above.
CREATE INDEX idx_transaction_donor_search_name_receipt_trgm
    ON cf.transaction USING GIN (LOWER(contributor_name_raw) gin_trgm_ops)
    WHERE contributor_name_raw IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';
CREATE INDEX idx_transaction_donor_search_employer_receipt_trgm
    ON cf.transaction USING GIN (LOWER(contributor_employer) gin_trgm_ops)
    WHERE contributor_employer IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';
CREATE INDEX idx_transaction_donor_search_zip5_receipt
    ON cf.transaction (LEFT(contributor_zip, 5))
    WHERE contributor_zip IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';

CREATE TABLE cf.candidate_committee_link (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id         UUID NOT NULL REFERENCES cf.candidate(id),
    committee_id         UUID NOT NULL REFERENCES cf.committee(id),
    election_id          UUID REFERENCES cf.election(id),
    designation          TEXT,
    candidate_election_year SMALLINT,
    fec_election_year    SMALLINT,
    valid_period         daterange NOT NULL,
    date_precision       core.date_precision NOT NULL DEFAULT 'year',
    source_record_id     UUID REFERENCES core.source_record(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_candidate_committee_link_period_non_empty
        CHECK (NOT isempty(valid_period)),
    CONSTRAINT candidate_committee_link_non_overlapping
        EXCLUDE USING gist (
            candidate_id WITH =,
            committee_id WITH =,
            (designation IS NULL) WITH =,
            COALESCE(designation, '') WITH =,
            valid_period WITH &&
        )
);

CREATE INDEX idx_candidate_committee_candidate_lookup
    ON cf.candidate_committee_link (candidate_id);
CREATE INDEX idx_candidate_committee_committee_lookup
    ON cf.candidate_committee_link (committee_id);
CREATE INDEX idx_candidate_committee_election_lookup
    ON cf.candidate_committee_link (election_id);
CREATE INDEX idx_candidate_committee_link_source_record_id
    ON cf.candidate_committee_link (source_record_id);
-- GiST index on (candidate_id, committee_id, designation null-flag/value, valid_period) is
-- already created by the candidate_committee_link_non_overlapping EXCLUDE constraint.

CREATE TABLE cf.nc_committee_registry (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_group_id     INTEGER NOT NULL,
    sboe_id          TEXT NOT NULL,
    committee_name   TEXT NOT NULL,
    status_desc      TEXT NOT NULL,
    old_id           TEXT,
    candidate_name   TEXT,
    data_source_id   UUID NOT NULL REFERENCES core.data_source(id),
    first_seen_at    TIMESTAMPTZ NOT NULL,
    last_seen_at     TIMESTAMPTZ NOT NULL,
    -- last_filing_date: most recent filing date observed for this committee.
    -- Populated by downstream filing ingest, NULL if no filings have been observed.
    -- Used by the NC orchestrator (orchestrator_progress.seed_progress_from_registry)
    -- to filter "recently active" committees within a window.
    last_filing_date DATE,
    -- is_active: derived from status_desc. Authoritative committee state from CFOrgLkup
    -- discovery uses the values 'ACTIVE (NON-EXEMPT)', 'ACTIVE (EXEMPT)', 'INACTIVE',
    -- 'CLOSED', 'CLOSED (PENDING)', 'CONDITIONALLY CLOSED', 'TERMINATED'. Active rows
    -- are exactly those whose status_desc starts with 'ACTIVE'. Stored as a generated
    -- column so the orchestrator filter stays in sync with discovery state without
    -- requiring the registry loader to know about orchestrator semantics.
    is_active        BOOLEAN GENERATED ALWAYS AS (status_desc LIKE 'ACTIVE%') STORED,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_nc_committee_registry_seen_order
        CHECK (last_seen_at >= first_seen_at)
);

CREATE UNIQUE INDEX uq_nc_committee_registry_org_group_id
    ON cf.nc_committee_registry (org_group_id);
CREATE INDEX idx_nc_committee_registry_sboe_id
    ON cf.nc_committee_registry (sboe_id);
CREATE INDEX idx_nc_committee_registry_status_desc
    ON cf.nc_committee_registry (status_desc);

CREATE TRIGGER trg_committee_updated_at
    BEFORE UPDATE ON cf.committee
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_committee_summary_updated_at
    BEFORE UPDATE ON cf.committee_summary
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_stage4_resume_checkpoint_updated_at
    BEFORE UPDATE ON cf.stage4_resume_checkpoint
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_candidate_updated_at
    BEFORE UPDATE ON cf.candidate
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_election_updated_at
    BEFORE UPDATE ON cf.election
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_filing_updated_at
    BEFORE UPDATE ON cf.filing
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_transaction_updated_at
    BEFORE UPDATE ON cf.transaction
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_candidate_committee_link_updated_at
    BEFORE UPDATE ON cf.candidate_committee_link
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_nc_committee_registry_updated_at
    BEFORE UPDATE ON cf.nc_committee_registry
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();
