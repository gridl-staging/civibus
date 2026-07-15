-- Civic Domain Tables: Office, ElectoralDivision, Contest, Candidacy, Officeholding
-- These are persistent domain nodes owned by domains/civics/ (ADR 0008).
-- They provide canonical civic abstractions across jurisdictions without
-- replacing existing source-shaped tables (e.g., cf.candidate, cf.election).
--
-- Migration order: 8 of 9 — run AFTER core (01–05), campaign_finance (06),
--   and property (07). Run BEFORE AGE graph bootstrap (09).
--   Defines: civic schema with 5 tables
--   Requires: core schema (entities.sql, jurisdiction.sql, provenance.sql)
--
-- PostgreSQL schema: civic (NOT civibus — that is the AGE graph schema)

CREATE SCHEMA IF NOT EXISTS civic;

-- ============================================================================
-- Office
-- ============================================================================
-- A named governmental position. Examples: "US House of Representatives",
-- "Governor", "County Commissioner". Deterministic keys derived from
-- office_level + state + name. Jurisdiction_id links to core.jurisdiction
-- for reference FIPS data when applicable.

CREATE TABLE civic.office (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name              TEXT NOT NULL,
    office_level      TEXT NOT NULL CHECK (office_level IN (
                          'federal', 'state', 'county', 'municipal',
                          'judicial', 'school_board', 'special_district'
                      )),
    title             TEXT,                       -- Formal title: "Representative", "Senator"
    jurisdiction_id   UUID REFERENCES core.jurisdiction(id),
    state             TEXT CHECK (
                          state IS NULL OR state ~ '^[A-Z]{2}$'
                      ),                          -- Two-letter state code (NULL for federal-wide)
    electoral_division_id UUID,
    is_elected        BOOLEAN NOT NULL DEFAULT TRUE,
    number_of_seats   SMALLINT NOT NULL DEFAULT 1 CHECK (number_of_seats >= 1),
    source_record_id  UUID,                       -- FK to core.source_record
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_office_canonical_key
    ON civic.office (
        office_level,
        COALESCE(state, ''),
        name,
        COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );

CREATE INDEX idx_office_name_trgm ON civic.office USING GIN (name gin_trgm_ops);
CREATE INDEX idx_office_level ON civic.office (office_level);
CREATE INDEX idx_office_state ON civic.office (state) WHERE state IS NOT NULL;
CREATE INDEX idx_office_jurisdiction ON civic.office (jurisdiction_id) WHERE jurisdiction_id IS NOT NULL;
CREATE INDEX idx_office_electoral_division ON civic.office (electoral_division_id)
    WHERE electoral_division_id IS NOT NULL;
CREATE INDEX idx_office_source_record_id ON civic.office (source_record_id);

-- ============================================================================
-- Office Roster Link
-- ============================================================================
-- Bridge table connecting canonical offices to canonical roster data sources.
-- This remains source-registry metadata only: filing-level provenance is still
-- owned by core.source_record + core.entity_source.

CREATE TABLE civic.office_roster_link (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    office_id         UUID NOT NULL REFERENCES civic.office(id),
    data_source_id    UUID NOT NULL REFERENCES core.data_source(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_office_roster_link_pair UNIQUE (office_id, data_source_id)
);

CREATE INDEX idx_office_roster_link_office_id ON civic.office_roster_link (office_id);
CREATE INDEX idx_office_roster_link_data_source_id ON civic.office_roster_link (data_source_id);

-- ============================================================================
-- Electoral Division
-- ============================================================================
-- Geographic or administrative boundary for elections. Tied to redistricting
-- cycles via boundary_year. Examples: "NC Congressional District 1 (2020)",
-- "Durham County", "NC State Senate District 20".

CREATE TABLE civic.electoral_division (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name              TEXT NOT NULL,
    division_type     TEXT NOT NULL CHECK (division_type IN (
                          'congressional_district', 'state_legislative_upper',
                          'state_legislative_lower', 'county', 'municipal',
                          'judicial_district', 'school_district', 'special_district',
                          'at_large', 'statewide'
                      )),
    state             TEXT CHECK (
                          state IS NULL OR state ~ '^[A-Z]{2}$'
                      ),                          -- Two-letter state code
    district_number   TEXT,                       -- "01", "12", etc.
    ocd_id            TEXT CHECK (
                          ocd_id IS NULL OR ocd_id LIKE 'ocd-division/%'
                      ),                          -- Open Civic Data ID (Stage 4)
    geometry          GEOMETRY(MultiPolygon, 4326),
    is_container      BOOLEAN NOT NULL DEFAULT FALSE,
    parent_id         UUID REFERENCES civic.electoral_division(id),
    boundary_year     SMALLINT CHECK (
                          boundary_year IS NULL OR boundary_year >= 0
                      ),                          -- Redistricting cycle year
    source_record_id  UUID,                       -- FK to core.source_record
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_electoral_division_canonical_key
    ON civic.electoral_division (
        division_type,
        COALESCE(state, ''),
        name,
        COALESCE(boundary_year, 0)
    );

CREATE INDEX idx_electoral_division_type ON civic.electoral_division (division_type);
CREATE INDEX idx_electoral_division_state ON civic.electoral_division (state) WHERE state IS NOT NULL;
CREATE UNIQUE INDEX uq_electoral_division_ocd_id ON civic.electoral_division (ocd_id) WHERE ocd_id IS NOT NULL;
CREATE INDEX idx_electoral_division_ocd_id ON civic.electoral_division (ocd_id) WHERE ocd_id IS NOT NULL;
CREATE INDEX idx_electoral_division_geometry
    ON civic.electoral_division USING GIST (geometry)
    WHERE geometry IS NOT NULL;
CREATE INDEX idx_electoral_division_source_record_id
    ON civic.electoral_division (source_record_id);

ALTER TABLE civic.office
    ADD CONSTRAINT fk_office_electoral_division
    FOREIGN KEY (electoral_division_id) REFERENCES civic.electoral_division(id);

-- ============================================================================
-- Election
-- ============================================================================
-- Canonical election event for a jurisdiction scope. This normalizes election
-- identity for reuse by contests, filing deadlines, and reporting periods.

CREATE TABLE civic.election (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    jurisdiction_scope    TEXT NOT NULL CHECK (jurisdiction_scope IN (
                              'federal', 'state', 'county', 'municipal', 'judicial',
                              'school_district', 'special_district'
                          )),
    state                 TEXT CHECK (
                              state IS NULL OR state ~ '^[A-Z]{2}$'
                          ),
    county                TEXT,
    municipality          TEXT,
    election_date         DATE NOT NULL,
    election_type         TEXT NOT NULL CHECK (election_type IN (
                              'general', 'primary', 'runoff', 'special', 'recall'
                          )),
    is_special            BOOLEAN NOT NULL DEFAULT FALSE,
    office_id             UUID REFERENCES civic.office(id),
    electoral_division_id UUID REFERENCES civic.electoral_division(id),
    source_record_id      UUID,                   -- FK to core.source_record
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_election_natural_key
    ON civic.election (
        jurisdiction_scope,
        COALESCE(state, ''),
        COALESCE(county, ''),
        COALESCE(municipality, ''),
        election_date,
        election_type,
        is_special,
        COALESCE(office_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid)
    );

CREATE INDEX idx_election_date ON civic.election (election_date);
CREATE INDEX idx_election_scope ON civic.election (jurisdiction_scope);
CREATE INDEX idx_election_state ON civic.election (state) WHERE state IS NOT NULL;
CREATE INDEX idx_civic_election_source_record_id ON civic.election (source_record_id);

-- ============================================================================
-- Contest
-- ============================================================================
-- A specific race or ballot question in a specific election. Links an office
-- to a time and (optionally) an electoral division. Deterministic keying by
-- office + division + election_date + election_type.

CREATE TABLE civic.contest (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                  TEXT NOT NULL,
    election_date         DATE,
    election_type         TEXT NOT NULL CHECK (election_type IN (
                              'general', 'primary', 'runoff', 'special', 'recall'
                          )),
    office_id             UUID NOT NULL REFERENCES civic.office(id),
    election_id           UUID REFERENCES civic.election(id),
    electoral_division_id UUID REFERENCES civic.electoral_division(id),
    number_of_seats       SMALLINT NOT NULL DEFAULT 1 CHECK (number_of_seats >= 1),
    filing_deadline       DATE,
    is_partisan           BOOLEAN NOT NULL DEFAULT TRUE,
    candidate_list_incomplete BOOLEAN NOT NULL DEFAULT FALSE,
    source_record_id      UUID,                   -- FK to core.source_record
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_contest_canonical_key
    ON civic.contest (
        office_id,
        COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(election_date, '0001-01-01'::date),
        election_type
    );

CREATE INDEX idx_contest_name_trgm ON civic.contest USING GIN (name gin_trgm_ops);
CREATE INDEX idx_contest_office ON civic.contest (office_id);
CREATE INDEX idx_contest_electoral_division ON civic.contest (electoral_division_id)
    WHERE electoral_division_id IS NOT NULL;
CREATE INDEX idx_contest_election_id ON civic.contest (election_id) WHERE election_id IS NOT NULL;
CREATE INDEX idx_contest_election_date ON civic.contest (election_date) WHERE election_date IS NOT NULL;
CREATE INDEX idx_civic_contest_source_record_id ON civic.contest (source_record_id);

-- ============================================================================
-- Contest Result
-- ============================================================================
-- Canonical candidate-level result rows for one contest and one source record.

CREATE TABLE civic.contest_result (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contest_id        UUID NOT NULL REFERENCES civic.contest(id),
    source_record_id  UUID NOT NULL REFERENCES core.source_record(id),
    candidate_name    TEXT NOT NULL,
    party             TEXT,
    votes             INTEGER NOT NULL CHECK (votes >= 0),
    vote_pct          NUMERIC(6,2) CHECK (vote_pct IS NULL OR (vote_pct >= 0 AND vote_pct <= 100)),
    is_certified      BOOLEAN NOT NULL DEFAULT FALSE,
    is_winner         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_contest_result_canonical UNIQUE (contest_id, source_record_id, candidate_name)
);

CREATE INDEX idx_contest_result_contest_id ON civic.contest_result (contest_id);
CREATE INDEX idx_contest_result_source_record_id ON civic.contest_result (source_record_id);

-- ============================================================================
-- Filing Deadline
-- ============================================================================
-- Filing windows and cutoffs associated with elections and offices.

CREATE TABLE civic.filing_deadline (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    election_id           UUID NOT NULL REFERENCES civic.election(id),
    office_id             UUID NOT NULL REFERENCES civic.office(id),
    electoral_division_id UUID REFERENCES civic.electoral_division(id),
    -- Jurisdiction columns are intentionally denormalized for direct filtering
    -- without requiring a join to civic.election. Loaders must copy these values
    -- from the linked election row to keep both representations consistent.
    jurisdiction_scope    TEXT NOT NULL CHECK (jurisdiction_scope IN (
                              'federal', 'state', 'county', 'municipal', 'judicial',
                              'school_district', 'special_district'
                          )),
    state                 TEXT CHECK (
                              state IS NULL OR state ~ '^[A-Z]{2}$'
                          ),
    county                TEXT,
    municipality          TEXT,
    deadline_date         DATE NOT NULL,
    deadline_kind         TEXT NOT NULL CHECK (deadline_kind IN (
                              'candidate_filing_open', 'candidate_filing', 'candidate_withdrawal', 'ballot_access'
                          )),
    source_record_id      UUID,                   -- FK to core.source_record
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_filing_deadline_natural_key
    ON civic.filing_deadline (
        election_id,
        office_id,
        COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid),
        deadline_kind
    );

CREATE INDEX idx_filing_deadline_date ON civic.filing_deadline (deadline_date);
CREATE INDEX idx_filing_deadline_scope ON civic.filing_deadline (jurisdiction_scope);
CREATE INDEX idx_filing_deadline_source_record_id ON civic.filing_deadline (source_record_id);

-- ============================================================================
-- Reporting Period
-- ============================================================================
-- Reporting period windows and due dates associated with elections.

CREATE TABLE civic.reporting_period (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    election_id           UUID NOT NULL REFERENCES civic.election(id),
    period_name           TEXT NOT NULL,
    period_start          DATE NOT NULL,
    period_end            DATE NOT NULL,
    report_due_date       DATE NOT NULL,
    is_pre_election       BOOLEAN NOT NULL DEFAULT FALSE,
    is_post_election      BOOLEAN NOT NULL DEFAULT FALSE,
    disclosure_kind       TEXT CHECK (disclosure_kind IN (
                              'periodic', 'pre_election', 'post_election', 'special'
                          )),
    source_record_id      UUID,                   -- FK to core.source_record
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_reporting_period_date_order CHECK (period_end >= period_start)
);

CREATE UNIQUE INDEX uq_reporting_period_natural_key
    ON civic.reporting_period (election_id, period_name);

CREATE INDEX idx_reporting_period_range ON civic.reporting_period (period_start, period_end);
CREATE INDEX idx_reporting_period_due_date ON civic.reporting_period (report_due_date);
CREATE INDEX idx_reporting_period_source_record_id ON civic.reporting_period (source_record_id);

-- ============================================================================
-- Candidacy
-- ============================================================================
-- A person's candidacy for a specific contest. Links a core.person to a
-- civic.contest with party, filing status, and incumbent/challenger info.

CREATE TABLE civic.candidacy (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id         UUID NOT NULL REFERENCES core.person(id),
    contest_id        UUID NOT NULL REFERENCES civic.contest(id),
    party             TEXT,
    name_on_ballot    TEXT,                       -- Ballot display name captured from source
    is_unexpired_term BOOLEAN NOT NULL DEFAULT FALSE, -- Unexpired-term indicator from source feed
    raw_fields        JSONB NOT NULL DEFAULT '{}'::jsonb, -- Full source row snapshot for provenance/debugging
    committee_id      UUID REFERENCES cf.committee(id), -- Optional canonical committee UUID when present
    filing_date       DATE,
    status            TEXT,                       -- filed, qualified, withdrawn, winner, lost
    incumbent_challenge TEXT,                     -- I, C, O (FEC convention)
    candidate_number  TEXT,                       -- Source-assigned candidate number
    source_record_id  UUID,                       -- FK to core.source_record
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_candidacy_canonical_key
    ON civic.candidacy (person_id, contest_id);

CREATE INDEX idx_candidacy_person ON civic.candidacy (person_id);
CREATE INDEX idx_candidacy_contest ON civic.candidacy (contest_id);
CREATE INDEX idx_candidacy_status ON civic.candidacy (status) WHERE status IS NOT NULL;
CREATE INDEX idx_candidacy_committee_id ON civic.candidacy (committee_id) WHERE committee_id IS NOT NULL;
CREATE INDEX idx_candidacy_name_on_ballot ON civic.candidacy (name_on_ballot) WHERE name_on_ballot IS NOT NULL;
CREATE INDEX idx_candidacy_source_record_id ON civic.candidacy (source_record_id);

-- ============================================================================
-- Officeholding
-- ============================================================================
-- Time-bounded record of who holds a governmental office. Uses daterange
-- with WITHOUT OVERLAPS to prevent duplicate concurrent holdings for the
-- same person+office combination.

CREATE TABLE civic.officeholding (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id             UUID NOT NULL REFERENCES core.person(id),
    office_id             UUID NOT NULL REFERENCES civic.office(id),
    electoral_division_id UUID REFERENCES civic.electoral_division(id),
    holder_status         TEXT NOT NULL DEFAULT 'elected' CHECK (holder_status IN (
                              'elected', 'appointed', 'acting', 'former'
                          )),
    valid_period          daterange NOT NULL DEFAULT daterange(NULL, NULL, '[)'),
    date_precision        core.date_precision NOT NULL DEFAULT 'day',
    source_record_id      UUID,                   -- FK to core.source_record
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_officeholding_canonical_key UNIQUE (person_id, office_id, valid_period WITHOUT OVERLAPS)
);

CREATE INDEX idx_officeholding_person ON civic.officeholding (person_id);
CREATE INDEX idx_officeholding_office ON civic.officeholding (office_id);
CREATE INDEX idx_officeholding_current ON civic.officeholding (person_id, office_id)
    WHERE upper_inf(valid_period);
CREATE INDEX idx_officeholding_source_record_id ON civic.officeholding (source_record_id);

-- ============================================================================
-- ZCTA District Reference
-- ============================================================================
-- Approximate ZCTA5 -> 119th congressional district mapping derived from the
-- Census 2020-ZCTA relationship file. This is a static reference table for
-- fundraising geography summaries, not a geometry join owner.

CREATE TABLE civic.zcta_district (
    zcta5           TEXT NOT NULL CHECK (zcta5 ~ '^[0-9]{5}$'),
    boundary_year   SMALLINT NOT NULL CHECK (boundary_year >= 0),
    state_fips      TEXT NOT NULL CHECK (state_fips ~ '^[0-9]{2}$'),
    cd_geoid        TEXT NOT NULL CHECK (cd_geoid ~ '^[0-9A-Z]{4}$'),
    district_number TEXT NOT NULL CHECK (char_length(district_number) = 2),
    land_share      NUMERIC(7,5) NOT NULL CHECK (land_share >= 0 AND land_share <= 1),
    source_url      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (zcta5, boundary_year)
);

CREATE INDEX idx_zcta_district_cd_geoid_boundary_year ON civic.zcta_district (cd_geoid, boundary_year);
CREATE INDEX idx_zcta_district_state_fips_boundary_year ON civic.zcta_district (state_fips, boundary_year);

COMMENT ON TABLE civic.zcta_district IS
    'Approximate ZCTA5-to-119th-congressional-district mapping derived from the Census 2020-ZCTA relationship file for fundraising geography summaries; not a parcel- or geometry-level district assignment.';

-- ============================================================================
-- Cross-schema foreign keys: source_record_id
-- ============================================================================
-- Applied here (not in provenance.sql) because these are domain tables.
-- Stage 3 will expand provenance CHECK constraints to cover civic types.

ALTER TABLE civic.office
    ADD CONSTRAINT fk_office_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.electoral_division
    ADD CONSTRAINT fk_electoral_division_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.contest
    ADD CONSTRAINT fk_contest_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.election
    ADD CONSTRAINT fk_election_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.filing_deadline
    ADD CONSTRAINT fk_filing_deadline_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.reporting_period
    ADD CONSTRAINT fk_reporting_period_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.candidacy
    ADD CONSTRAINT fk_candidacy_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

ALTER TABLE civic.officeholding
    ADD CONSTRAINT fk_officeholding_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

-- ============================================================================
-- Reference Seed Data (Stage 4)
-- ============================================================================
-- Deterministic office and electoral-division reference rows for federal + WA + FL.
-- These are stable inventory rows that downstream loaders can map against.
-- Inserts are idempotent so db-reset and repeated schema applies remain safe.

INSERT INTO core.jurisdiction (
    id,
    name,
    jurisdiction_type,
    fips,
    state
)
VALUES
    ('00000000-0000-4000-8000-000000000901', 'Washington', 'state', '53', 'WA'),
    ('00000000-0000-4000-8000-000000000902', 'Florida', 'state', '12', 'FL')
ON CONFLICT (fips) WHERE fips IS NOT NULL DO UPDATE
SET
    name = EXCLUDED.name,
    jurisdiction_type = EXCLUDED.jurisdiction_type,
    state = EXCLUDED.state;

INSERT INTO civic.office (
    id,
    name,
    office_level,
    title,
    jurisdiction_id,
    state,
    is_elected,
    number_of_seats
)
VALUES
    -- FEC H/S/P expansion into canonical offices
    ('00000000-0000-4000-8000-000000000101', 'us_house', 'federal', 'Representative', NULL, NULL, TRUE, 435),
    ('00000000-0000-4000-8000-000000000102', 'us_senate', 'federal', 'Senator', NULL, NULL, TRUE, 100),
    ('00000000-0000-4000-8000-000000000103', 'us_president', 'federal', 'President', NULL, NULL, TRUE, 1),
    ('00000000-0000-4000-8000-000000000104', 'us_vice_president', 'federal', 'Vice President', NULL, NULL, TRUE, 1),
    ('00000000-0000-4000-8000-000000000105', 'us_house_delegate', 'federal', 'Delegate', NULL, NULL, TRUE, 6),

    -- WA office levels (15) from state config coverage.office_levels
    ('00000000-0000-4000-8000-000000000201', 'attorney_general', 'state', 'Attorney General', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000202', 'commissioner_of_public_lands', 'state', 'Commissioner of Public Lands', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000203', 'county', 'county', 'County Office', NULL, 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000204', 'governor', 'state', 'Governor', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000205', 'insurance_commissioner', 'state', 'Insurance Commissioner', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000206', 'lieutenant_governor', 'state', 'Lieutenant Governor', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000207', 'municipal', 'municipal', 'Municipal Office', NULL, 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000208', 'school_district', 'school_board', 'School Board Office', NULL, 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000209', 'secretary_of_state', 'state', 'Secretary of State', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000210', 'special_district', 'special_district', 'Special District Office', NULL, 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000211', 'state_auditor', 'state', 'State Auditor', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000212', 'state_house', 'state', 'State House', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000213', 'state_senate', 'state', 'State Senate', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000214', 'state_treasurer', 'state', 'State Treasurer', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),
    ('00000000-0000-4000-8000-000000000215', 'superintendent_of_public_instruction', 'state', 'Superintendent of Public Instruction', (SELECT id FROM core.jurisdiction WHERE fips = '53' LIMIT 1), 'WA', TRUE, 1),

    -- FL office levels (11) from state config coverage.office_levels
    ('00000000-0000-4000-8000-000000000301', 'attorney_general', 'state', 'Attorney General', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000302', 'chief_financial_officer', 'state', 'Chief Financial Officer', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000303', 'commissioner_of_agriculture', 'state', 'Commissioner of Agriculture', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000304', 'county', 'county', 'County Office', NULL, 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000305', 'governor', 'state', 'Governor', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000306', 'lieutenant_governor', 'state', 'Lieutenant Governor', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000307', 'municipal', 'municipal', 'Municipal Office', NULL, 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000308', 'school_district', 'school_board', 'School Board Office', NULL, 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000309', 'special_district', 'special_district', 'Special District Office', NULL, 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000310', 'state_house', 'state', 'State House', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1),
    ('00000000-0000-4000-8000-000000000311', 'state_senate', 'state', 'State Senate', (SELECT id FROM core.jurisdiction WHERE fips = '12' LIMIT 1), 'FL', TRUE, 1)
ON CONFLICT DO NOTHING;

UPDATE civic.office AS office
SET jurisdiction_id = jurisdiction.id
FROM core.jurisdiction AS jurisdiction
WHERE office.office_level = 'state'
  AND office.state IN ('WA', 'FL')
  AND jurisdiction.fips = CASE office.state
      WHEN 'WA' THEN '53'
      WHEN 'FL' THEN '12'
      ELSE NULL
  END
  AND office.jurisdiction_id IS DISTINCT FROM jurisdiction.id;

INSERT INTO civic.electoral_division (
    id,
    name,
    division_type,
    state,
    district_number,
    ocd_id,
    is_container,
    parent_id,
    boundary_year
)
VALUES
    -- Actual statewide divisions with official OCD-IDs.
    ('00000000-0000-4000-8000-000000000501', 'us', 'statewide', NULL, NULL, 'ocd-division/country:us', FALSE, NULL, NULL),
    ('00000000-0000-4000-8000-000000000502', 'wa', 'statewide', 'WA', NULL, 'ocd-division/country:us/state:wa', FALSE, '00000000-0000-4000-8000-000000000501', NULL),
    ('00000000-0000-4000-8000-000000000503', 'fl', 'statewide', 'FL', NULL, 'ocd-division/country:us/state:fl', FALSE, '00000000-0000-4000-8000-000000000501', NULL),
    -- Hierarchy-only grouping rows. Later loaders should not treat these as actual browseable districts.
    ('00000000-0000-4000-8000-000000000504', 'us_congressional_districts', 'congressional_district', NULL, NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000501', 2022),
    ('00000000-0000-4000-8000-000000000505', 'wa_state_senate_districts', 'state_legislative_upper', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', 2020),
    ('00000000-0000-4000-8000-000000000506', 'wa_state_house_districts', 'state_legislative_lower', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', 2020),
    ('00000000-0000-4000-8000-000000000507', 'wa_counties', 'county', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', NULL),
    ('00000000-0000-4000-8000-000000000508', 'wa_municipalities', 'municipal', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', NULL),
    ('00000000-0000-4000-8000-000000000509', 'wa_school_districts', 'school_district', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', NULL),
    ('00000000-0000-4000-8000-000000000510', 'wa_special_districts', 'special_district', 'WA', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000502', NULL),
    ('00000000-0000-4000-8000-000000000511', 'fl_state_senate_districts', 'state_legislative_upper', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', 2022),
    ('00000000-0000-4000-8000-000000000512', 'fl_state_house_districts', 'state_legislative_lower', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', 2022),
    ('00000000-0000-4000-8000-000000000513', 'fl_counties', 'county', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', NULL),
    ('00000000-0000-4000-8000-000000000514', 'fl_municipalities', 'municipal', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', NULL),
    ('00000000-0000-4000-8000-000000000515', 'fl_school_districts', 'school_district', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', NULL),
    ('00000000-0000-4000-8000-000000000516', 'fl_special_districts', 'special_district', 'FL', NULL, NULL, TRUE, '00000000-0000-4000-8000-000000000503', NULL)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- Triggers: auto-update updated_at
-- ============================================================================

CREATE TRIGGER trg_office_updated_at
    BEFORE UPDATE ON civic.office
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_office_roster_link_updated_at
    BEFORE UPDATE ON civic.office_roster_link
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_electoral_division_updated_at
    BEFORE UPDATE ON civic.electoral_division
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_contest_updated_at
    BEFORE UPDATE ON civic.contest
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_contest_result_updated_at
    BEFORE UPDATE ON civic.contest_result
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_election_updated_at
    BEFORE UPDATE ON civic.election
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_filing_deadline_updated_at
    BEFORE UPDATE ON civic.filing_deadline
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_reporting_period_updated_at
    BEFORE UPDATE ON civic.reporting_period
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_candidacy_updated_at
    BEFORE UPDATE ON civic.candidacy
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_officeholding_updated_at
    BEFORE UPDATE ON civic.officeholding
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
