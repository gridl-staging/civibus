-- Persist the typed contribution-limit rule contract for initialized databases.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

-- Required by the non-overlapping-periods EXCLUDE constraint below (gist equality on
-- the scalar dimension columns). Initialized databases already load this via
-- core/schema/entities.sql; the guard keeps the migration self-contained and idempotent.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS cf.contribution_limit_rules (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    jurisdiction_fips        TEXT NOT NULL,
    donor_type               TEXT,
    recipient_type           TEXT,
    office_level             TEXT,
    election_type            TEXT,
    limit_status             TEXT NOT NULL,
    limit_amount             INTEGER,
    limit_basis              TEXT,
    source_citation          TEXT NOT NULL,
    effective_date           DATE,
    sunset_date              DATE,
    research_observed_date   DATE,
    local_override_allowed   BOOLEAN NOT NULL DEFAULT FALSE,
    note                     TEXT,
    metadata                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_contribution_limit_rules_status
        CHECK (limit_status IN ('numeric', 'prohibited', 'unlimited', 'no_statutory_limit', 'unknown')),
    CONSTRAINT ck_contribution_limit_rules_basis
        CHECK (limit_basis IS NULL OR limit_basis IN ('per_election', 'per_cycle', 'per_calendar_year')),
    CONSTRAINT ck_contribution_limit_rules_donor_type
        CHECK (
            donor_type IS NULL OR donor_type IN (
                'individual',
                'pac',
                'party_committee',
                'corporation',
                'union',
                'small_donor_committee',
                'small_contributor_committee',
                'candidate',
                'self',
                'issue_committee',
                'ie_committee'
            )
        ),
    CONSTRAINT ck_contribution_limit_rules_recipient_type
        CHECK (
            recipient_type IS NULL OR recipient_type IN (
                'candidate_committee',
                'party_committee',
                'pac',
                'issue_committee',
                'ie_committee',
                'ballot_measure_committee'
            )
        ),
    CONSTRAINT ck_contribution_limit_rules_office_level
        CHECK (
            office_level IS NULL OR office_level IN (
                'attorney_general',
                'board_of_equalization',
                'board_of_supervisors',
                'borough_president',
                'city_attorney',
                'city_commissioners',
                'city_council',
                'controller',
                'cu_regent',
                'district_attorney',
                'governor',
                'insurance_commissioner',
                'judicial',
                'lieutenant_governor',
                'mayor',
                'public_advocate',
                'register_of_wills',
                'secretary_of_state',
                'sheriff',
                'state_board_of_education',
                'state_controller',
                'state_house',
                'state_senate',
                'state_treasurer',
                'superintendent_of_public_instruction',
                'citywide',
                'county',
                'municipal',
                'school_district',
                'special_district',
                'rtd',
                'statewide',
                'statewide_except_governor',
                'legislative',
                'other_office'
            )
        ),
    CONSTRAINT ck_contribution_limit_rules_election_type
        CHECK (election_type IS NULL OR election_type IN ('primary', 'general', 'runoff', 'special', 'recall')),
    CONSTRAINT ck_contribution_limit_rules_numeric_fields
        CHECK (
            limit_status <> 'numeric' OR (
                limit_amount IS NOT NULL
                AND limit_basis IS NOT NULL
                AND effective_date IS NOT NULL
                AND research_observed_date IS NULL
            )
        ),
    CONSTRAINT ck_contribution_limit_rules_non_numeric_fields
        CHECK (
            limit_status NOT IN ('prohibited', 'unlimited', 'no_statutory_limit') OR (
                limit_amount IS NULL
                AND limit_basis IS NULL
                AND effective_date IS NOT NULL
                AND research_observed_date IS NULL
            )
        ),
    CONSTRAINT ck_contribution_limit_rules_unknown_fields
        CHECK (
            limit_status <> 'unknown' OR (
                limit_amount IS NULL
                AND limit_basis IS NULL
                AND effective_date IS NULL
                AND sunset_date IS NULL
                AND research_observed_date IS NOT NULL
                AND note IS NOT NULL
            )
        ),
    -- Blank detection mirrors config_schema.NonBlankText (Pydantic str.strip()):
    -- the class enumerates every code point Python's str.isspace() treats as
    -- whitespace, since POSIX \s / [:space:] miss U+0085/U+00A0 and the Zs spaces.
    CONSTRAINT ck_contribution_limit_rules_citation_nonblank
        CHECK (source_citation ~ E'[^\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000]'),
    CONSTRAINT ck_contribution_limit_rules_note_nonblank
        CHECK (note IS NULL OR note ~ E'[^\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000]'),
    CONSTRAINT ck_contribution_limit_rules_date_order
        CHECK (effective_date IS NULL OR sunset_date IS NULL OR sunset_date >= effective_date),
    CONSTRAINT ck_contribution_limit_rules_metadata_shape
        CHECK (
            jsonb_typeof(metadata) = 'array'
            -- Strict mode does not auto-unwrap arrays, so an array-valued item
            -- (e.g. [[{...}]]) is rejected here instead of being unwrapped to its
            -- inner object by the lax scan below. silent := true makes a non-array
            -- metadata value fail this CHECK cleanly rather than raise a jsonpath error.
            AND NOT jsonb_path_exists(metadata, 'strict $[*] ? (@.type() != "object")', '{}', true)
            AND NOT jsonb_path_exists(
                metadata,
                '$[*] ? (
                    @.type() != "object"
                    || !exists(@.description)
                    || @.description.type() != "string"
                    || !(@.description like_regex "[^\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000]")
                    || !exists(@.source_citation)
                    || @.source_citation.type() != "string"
                    || !(@.source_citation like_regex "[^\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000]")
                    || exists(
                        @.keyvalue().key ? (
                            @ != "description" && @ != "source_citation"
                        )
                    )
                )'
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_contribution_limit_rules_identity
    ON cf.contribution_limit_rules (
        jurisdiction_fips,
        (donor_type IS NULL),
        COALESCE(donor_type, ''),
        (recipient_type IS NULL),
        COALESCE(recipient_type, ''),
        (office_level IS NULL),
        COALESCE(office_level, ''),
        (election_type IS NULL),
        COALESCE(election_type, ''),
        (effective_date IS NULL),
        COALESCE(effective_date, DATE '0001-01-01'),
        (sunset_date IS NULL),
        COALESCE(sunset_date, DATE '0001-01-01')
    );

-- Temporal integrity guard (idempotent): see tables.sql for rationale. sunset_date is
-- exclusive, allowing a successor to take effect on the date its predecessor ceases.
-- Added after the identity index so an exact-tuple duplicate still reports that index.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cf.contribution_limit_rules'::regclass
          AND conname = 'contribution_limit_rules_non_overlapping_periods'
    ) THEN
        ALTER TABLE cf.contribution_limit_rules
            ADD CONSTRAINT contribution_limit_rules_non_overlapping_periods
            EXCLUDE USING gist (
        jurisdiction_fips WITH =,
        (donor_type IS NULL) WITH =,
        COALESCE(donor_type, '') WITH =,
        (recipient_type IS NULL) WITH =,
        COALESCE(recipient_type, '') WITH =,
        (office_level IS NULL) WITH =,
        COALESCE(office_level, '') WITH =,
        (election_type IS NULL) WITH =,
        COALESCE(election_type, '') WITH =,
        daterange(effective_date, sunset_date, '[)') WITH &&
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'cf.contribution_limit_rules'::regclass
          AND tgname = 'trg_contribution_limit_rules_updated_at'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_contribution_limit_rules_updated_at
            BEFORE UPDATE ON cf.contribution_limit_rules
            FOR EACH ROW
            EXECUTE FUNCTION core.set_updated_at();
    END IF;
END
$$;
