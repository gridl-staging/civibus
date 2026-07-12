-- IRS 527 Dark Money Schema
--
-- Prerequisites (loaded before this file):
--   - core/schema/entities.sql
--   - core/schema/provenance.sql
--   - domains/campaign_finance/schema/tables.sql  (creates cf schema)
--
-- Schema ownership
-- This file owns exactly four tables:
--   - cf.political_organization_527  (Form 8871 registration — record type 1)
--   - cf.filing_8872                 (Form 8872 periodic disclosure — record type 2)
--   - cf.contribution_527            (Schedule A contributions — record type A)
--   - cf.expenditure_527             (Schedule B expenditures — record type B)
--
-- Conventions:
--   - UUID primary keys use uuid_generate_v4().
--   - updated_at columns are maintained via core.set_updated_at().
--   - source_record_id links to core.source_record(id) for provenance.
--   - Natural-key unique constraints: EIN for orgs (latest 8871 wins on upsert),
--     form_id_number for filings, sched_a_id for contributions, sched_b_id for expenditures.
--   - EIN indexed on all four tables for cross-table joins.

-- ============================================================
-- cf.political_organization_527 — Form 8871 (record type 1)
-- ============================================================

CREATE TABLE cf.political_organization_527 (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    form_type                   TEXT NOT NULL,
    form_id_number              TEXT NOT NULL,
    ein                         TEXT NOT NULL,
    name                        TEXT NOT NULL,

    -- Mailing address
    mailing_address_1           TEXT,
    mailing_address_2           TEXT,
    mailing_address_city        TEXT,
    mailing_address_state       TEXT,
    mailing_address_zip         TEXT,
    mailing_address_zip_ext     TEXT,

    -- Business address
    business_address_1          TEXT,
    business_address_2          TEXT,
    business_address_city       TEXT,
    business_address_state      TEXT,
    business_address_zip        TEXT,
    business_address_zip_ext    TEXT,

    -- Contact info
    email_address               TEXT,
    custodian_name              TEXT,
    custodian_address_1         TEXT,
    custodian_address_2         TEXT,
    custodian_address_city      TEXT,
    custodian_address_state     TEXT,
    custodian_address_zip       TEXT,
    custodian_address_zip_ext   TEXT,
    contact_person_name         TEXT,
    contact_address_1           TEXT,
    contact_address_2           TEXT,
    contact_address_city        TEXT,
    contact_address_state       TEXT,
    contact_address_zip         TEXT,
    contact_address_zip_ext     TEXT,

    -- Organization details
    purpose                     TEXT,
    established_date            DATE,
    material_change_date        DATE,
    insert_datetime             TEXT,

    -- Report indicators
    initial_report_indicator    BOOLEAN,
    amended_report_indicator    BOOLEAN,
    final_report_indicator      BOOLEAN,

    -- Exemption indicators
    exempt_8872_indicator       BOOLEAN,
    exempt_state                TEXT,
    exempt_990_indicator        BOOLEAN,
    related_entity_bypass       TEXT,
    eain_bypass                 TEXT,

    -- Provenance
    source_record_id            UUID REFERENCES core.source_record(id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Natural key: EIN (latest 8871 wins on upsert)
    CONSTRAINT uq_political_org_527_ein UNIQUE (ein),

    CONSTRAINT ck_political_org_527_ein_format
        CHECK (ein ~ '^\d{2}-?\d{7}$')
);

-- ein already has an implicit index from the UNIQUE constraint
CREATE INDEX idx_political_org_527_form_id ON cf.political_organization_527 (form_id_number);
CREATE INDEX idx_political_organization_527_source_record_id
    ON cf.political_organization_527 (source_record_id);

-- ============================================================
-- cf.filing_8872 — Form 8872 periodic disclosure (record type 2)
-- ============================================================

CREATE TABLE cf.filing_8872 (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    form_type                   TEXT NOT NULL,
    form_id_number              TEXT NOT NULL,
    ein                         TEXT NOT NULL,
    period_begin_date           DATE,
    period_end_date             DATE,

    -- Organization info (denormalized from filing record)
    organization_name           TEXT,
    mailing_address_1           TEXT,
    mailing_address_2           TEXT,
    mailing_address_city        TEXT,
    mailing_address_state       TEXT,
    mailing_address_zip         TEXT,
    mailing_address_zip_ext     TEXT,
    email_address               TEXT,
    change_of_address_indicator BOOLEAN,
    org_formation_date          DATE,

    -- Custodian
    custodian_name              TEXT,
    custodian_address_1         TEXT,
    custodian_address_2         TEXT,
    custodian_address_city      TEXT,
    custodian_address_state     TEXT,
    custodian_address_zip       TEXT,
    custodian_address_zip_ext   TEXT,

    -- Contact
    contact_person_name         TEXT,
    contact_address_1           TEXT,
    contact_address_2           TEXT,
    contact_address_city        TEXT,
    contact_address_state       TEXT,
    contact_address_zip         TEXT,
    contact_address_zip_ext     TEXT,

    -- Business address
    business_address_1          TEXT,
    business_address_2          TEXT,
    business_address_city       TEXT,
    business_address_state      TEXT,
    business_address_zip        TEXT,
    business_address_zip_ext    TEXT,

    -- Report indicators
    initial_report_indicator    BOOLEAN,
    amended_report_indicator    BOOLEAN,
    final_report_indicator      BOOLEAN,

    -- Schedule/period indicators
    quarterly_indicator         BOOLEAN,
    monthly_report_month        TEXT,
    pre_election_type           TEXT,
    pre_or_post_election_date   DATE,
    pre_or_post_election_state  TEXT,

    -- Schedule totals
    sched_a_indicator           BOOLEAN,
    total_sched_a               NUMERIC(14, 2),
    sched_b_indicator           BOOLEAN,
    total_sched_b               NUMERIC(14, 2),
    insert_datetime             TEXT,

    -- Provenance
    source_record_id            UUID REFERENCES core.source_record(id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Natural key: form_id_number (one filing per form_id_number)
    CONSTRAINT uq_filing_8872_form_id UNIQUE (form_id_number),

    CONSTRAINT ck_filing_8872_coverage_order
        CHECK (period_begin_date IS NULL OR period_end_date IS NULL OR period_begin_date <= period_end_date),

    CONSTRAINT ck_filing_8872_ein_format
        CHECK (ein ~ '^\d{2}-?\d{7}$')
);

CREATE INDEX idx_filing_8872_ein ON cf.filing_8872 (ein);
CREATE INDEX idx_filing_8872_period ON cf.filing_8872 (period_begin_date, period_end_date);
CREATE INDEX idx_filing_8872_source_record_id ON cf.filing_8872 (source_record_id);

-- ============================================================
-- cf.contribution_527 — Schedule A (record type A)
-- ============================================================

CREATE TABLE cf.contribution_527 (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    form_id_number              TEXT NOT NULL,
    sched_a_id                  TEXT NOT NULL,
    ein                         TEXT NOT NULL,
    contributor_name            TEXT NOT NULL,
    amount                      NUMERIC(14, 2) NOT NULL,
    contribution_date           DATE,
    aggregate_ytd               NUMERIC(14, 2) NOT NULL,

    -- Optional org name (denormalized)
    org_name                    TEXT,

    -- Contributor address
    contributor_address_1       TEXT,
    contributor_address_2       TEXT,
    contributor_address_city    TEXT,
    contributor_address_state   TEXT,
    contributor_address_zip     TEXT,
    contributor_address_zip_ext TEXT,

    -- Contributor employment
    contributor_employer        TEXT,
    contributor_occupation      TEXT,

    -- Provenance
    source_record_id            UUID REFERENCES core.source_record(id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Natural key: sched_a_id
    CONSTRAINT uq_contribution_527_sched_a_id UNIQUE (sched_a_id),

    CONSTRAINT ck_contribution_527_ein_format
        CHECK (ein ~ '^\d{2}-?\d{7}$')
);

CREATE INDEX idx_contribution_527_ein ON cf.contribution_527 (ein);
CREATE INDEX idx_contribution_527_form_id ON cf.contribution_527 (form_id_number);
CREATE INDEX idx_contribution_527_date ON cf.contribution_527 (contribution_date);
CREATE INDEX idx_contribution_527_source_record_id ON cf.contribution_527 (source_record_id);

-- ============================================================
-- cf.expenditure_527 — Schedule B (record type B)
-- ============================================================

CREATE TABLE cf.expenditure_527 (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    form_id_number              TEXT NOT NULL,
    sched_b_id                  TEXT NOT NULL,
    ein                         TEXT NOT NULL,
    recipient_name              TEXT NOT NULL,
    amount                      NUMERIC(14, 2) NOT NULL,
    expenditure_date            DATE,
    purpose                     TEXT,

    -- Optional org name (denormalized)
    org_name                    TEXT,

    -- Recipient address (normalized from IRS "RECIEPIENT" typo)
    recipient_address_1         TEXT,
    recipient_address_2         TEXT,
    recipient_address_city      TEXT,
    recipient_address_state     TEXT,
    recipient_address_zip       TEXT,
    recipient_address_zip_ext   TEXT,

    -- Recipient employment
    recipient_employer          TEXT,
    recipient_occupation        TEXT,

    -- Provenance
    source_record_id            UUID REFERENCES core.source_record(id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Natural key: sched_b_id
    CONSTRAINT uq_expenditure_527_sched_b_id UNIQUE (sched_b_id),

    CONSTRAINT ck_expenditure_527_ein_format
        CHECK (ein ~ '^\d{2}-?\d{7}$')
);

CREATE INDEX idx_expenditure_527_ein ON cf.expenditure_527 (ein);
CREATE INDEX idx_expenditure_527_form_id ON cf.expenditure_527 (form_id_number);
CREATE INDEX idx_expenditure_527_date ON cf.expenditure_527 (expenditure_date);
CREATE INDEX idx_expenditure_527_source_record_id ON cf.expenditure_527 (source_record_id);

-- ============================================================
-- Triggers
-- ============================================================

CREATE TRIGGER trg_political_org_527_updated_at
    BEFORE UPDATE ON cf.political_organization_527
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_filing_8872_updated_at
    BEFORE UPDATE ON cf.filing_8872
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_contribution_527_updated_at
    BEFORE UPDATE ON cf.contribution_527
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_expenditure_527_updated_at
    BEFORE UPDATE ON cf.expenditure_527
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();
