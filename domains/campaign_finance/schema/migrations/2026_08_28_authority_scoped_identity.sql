-- Scope campaign-finance source and native-record identity by filing authority.
-- core.schema.apply_migrations executes the named phases under one pinned digest.

-- civibus-phase: prepare
ALTER TABLE core.data_source
    ADD COLUMN IF NOT EXISTS filing_authority_type TEXT,
    ADD COLUMN IF NOT EXISTS filing_authority_code TEXT;

UPDATE core.data_source
SET filing_authority_type = CASE
        WHEN split_part(lower(jurisdiction), '/', 1) = 'federal' THEN 'federal'
        WHEN split_part(lower(jurisdiction), '/', 1) IN ('state', 'states') THEN 'state'
        WHEN split_part(lower(jurisdiction), '/', 1) IN ('county', 'counties') THEN 'county'
        WHEN split_part(lower(jurisdiction), '/', 1) IN ('city', 'cities', 'municipality') THEN 'municipality'
        WHEN split_part(lower(jurisdiction), '/', 1) IN ('school', 'schools', 'school_district')
            THEN 'school_district'
        WHEN split_part(lower(jurisdiction), '/', 1) IN ('special', 'special_district')
            THEN 'special_district'
        ELSE 'named_other'
    END,
    filing_authority_code = CASE
        WHEN jurisdiction IS NULL OR btrim(jurisdiction) = '' THEN 'LEGACY_SOURCE:' || id::text
        WHEN split_part(lower(jurisdiction), '/', 1) IN (
            'federal', 'state', 'states', 'county', 'counties', 'city', 'cities',
            'municipality', 'school', 'schools', 'school_district', 'special',
            'special_district', 'named_other'
        ) AND position('/' IN jurisdiction) > 0
            THEN upper(btrim(substr(jurisdiction, position('/' IN jurisdiction) + 1)))
        ELSE upper(btrim(jurisdiction))
    END
WHERE domain = 'campaign_finance'
  AND (filing_authority_type IS NULL OR filing_authority_code IS NULL);

UPDATE core.data_source
SET filing_authority_type = lower(btrim(filing_authority_type)),
    filing_authority_code = upper(btrim(filing_authority_code))
WHERE filing_authority_type IS NOT NULL OR filing_authority_code IS NOT NULL;

CREATE OR REPLACE FUNCTION core.populate_campaign_finance_filing_authority()
RETURNS TRIGGER AS $$
DECLARE
    scope_type TEXT;
    scope_code TEXT;
BEGIN
    IF NEW.domain <> 'campaign_finance' THEN
        RETURN NEW;
    END IF;

    IF NEW.filing_authority_type IS NULL AND NEW.filing_authority_code IS NULL THEN
        IF lower(btrim(NEW.jurisdiction)) = 'federal' THEN
            NEW.filing_authority_type := 'federal';
            NEW.filing_authority_code := 'FEC';
        ELSIF position('/' IN NEW.jurisdiction) > 0 THEN
            scope_type := lower(btrim(split_part(NEW.jurisdiction, '/', 1)));
            scope_code := upper(btrim(substr(NEW.jurisdiction, position('/' IN NEW.jurisdiction) + 1)));
            scope_type := CASE scope_type
                WHEN 'states' THEN 'state'
                WHEN 'counties' THEN 'county'
                WHEN 'city' THEN 'municipality'
                WHEN 'cities' THEN 'municipality'
                WHEN 'schools' THEN 'school_district'
                WHEN 'school' THEN 'school_district'
                WHEN 'special' THEN 'special_district'
                ELSE scope_type
            END;
            IF scope_type IN (
                'federal', 'state', 'county', 'municipality',
                'school_district', 'special_district', 'named_other'
            ) AND scope_code <> '' THEN
                NEW.filing_authority_type := scope_type;
                NEW.filing_authority_code := scope_code;
            END IF;
        END IF;
    ELSIF NEW.filing_authority_type IS NOT NULL AND NEW.filing_authority_code IS NOT NULL THEN
        NEW.filing_authority_type := lower(btrim(NEW.filing_authority_type));
        NEW.filing_authority_code := upper(btrim(NEW.filing_authority_code));
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_data_source_campaign_finance_filing_authority ON core.data_source;
CREATE TRIGGER trg_data_source_campaign_finance_filing_authority
    BEFORE INSERT OR UPDATE OF domain, jurisdiction, filing_authority_type, filing_authority_code
    ON core.data_source
    FOR EACH ROW EXECUTE FUNCTION core.populate_campaign_finance_filing_authority();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'core.data_source'::regclass
          AND conname = 'ck_data_source_filing_authority_pair'
    ) THEN
        ALTER TABLE core.data_source ADD CONSTRAINT ck_data_source_filing_authority_pair CHECK (
            (filing_authority_type IS NULL) = (filing_authority_code IS NULL)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'core.data_source'::regclass
          AND conname = 'ck_data_source_campaign_finance_authority'
    ) THEN
        ALTER TABLE core.data_source ADD CONSTRAINT ck_data_source_campaign_finance_authority CHECK (
            domain <> 'campaign_finance'
            OR (filing_authority_type IS NOT NULL AND filing_authority_code IS NOT NULL)
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'core.data_source'::regclass
          AND conname = 'ck_data_source_filing_authority_type'
    ) THEN
        ALTER TABLE core.data_source ADD CONSTRAINT ck_data_source_filing_authority_type CHECK (
            filing_authority_type IS NULL OR filing_authority_type IN (
                'federal', 'state', 'county', 'municipality', 'school_district',
                'special_district', 'named_other'
            )
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'core.data_source'::regclass
          AND conname = 'ck_data_source_filing_authority_code'
    ) THEN
        ALTER TABLE core.data_source ADD CONSTRAINT ck_data_source_filing_authority_code CHECK (
            filing_authority_code IS NULL OR btrim(filing_authority_code) <> ''
        ) NOT VALID;
    END IF;
END $$;

CREATE OR REPLACE VIEW core.person_er_view AS
SELECT
    person.id,
    person.canonical_name,
    person.first_name,
    person.last_name,
    person.date_of_birth,
    address_choice.normalized_address,
    address_choice.street_number,
    address_choice.zip5,
    address_choice.state,
    person.identifiers->>'employer' AS employer,
    person.identifiers->>'occupation' AS occupation,
    identifier_choice.identifier_key,
    COALESCE(authority_choice.filing_authority_scopes, '{}'::text[]) AS filing_authority_scopes
FROM core.person AS person
LEFT JOIN LATERAL (
    SELECT address.normalized_address, address.street_number, address.zip5, address.state
    FROM core.entity_address AS entity_address
    JOIN core.address AS address ON address.id = entity_address.address_id
    WHERE entity_address.entity_type = 'person'
      AND entity_address.entity_id = person.id
      AND upper_inf(entity_address.valid_period)
    ORDER BY entity_address.created_at DESC, entity_address.id DESC
    LIMIT 1
) AS address_choice ON TRUE
LEFT JOIN LATERAL (
    SELECT identifier_item.key || ':' || btrim(identifier_item.value) AS identifier_key
    FROM jsonb_each_text(person.identifiers) AS identifier_item(key, value)
    WHERE identifier_item.key NOT IN ('employer', 'occupation', 'occupation_comments', 'llc_name')
      AND NULLIF(btrim(identifier_item.value), '') IS NOT NULL
) AS identifier_choice ON TRUE
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT data_source.filing_authority_type || ':' || data_source.filing_authority_code)
        AS filing_authority_scopes
    FROM core.entity_source AS entity_source
    JOIN core.source_record AS source_record ON source_record.id = entity_source.source_record_id
    JOIN core.data_source AS data_source ON data_source.id = source_record.data_source_id
    WHERE entity_source.entity_type = 'person'
      AND entity_source.entity_id = person.id
      AND data_source.domain = 'campaign_finance'
      AND data_source.filing_authority_type IS NOT NULL
) AS authority_choice ON TRUE;

CREATE OR REPLACE VIEW core.organization_er_view AS
SELECT
    organization.id,
    organization.canonical_name,
    organization.registered_state,
    address_choice.normalized_address,
    address_choice.zip5,
    organization.org_type,
    organization.identifiers,
    organization.identifiers->>'registered_agent_name' AS registered_agent_name,
    COALESCE(authority_choice.filing_authority_scopes, '{}'::text[]) AS filing_authority_scopes
FROM core.organization AS organization
LEFT JOIN LATERAL (
    SELECT address.normalized_address, address.zip5
    FROM core.entity_address AS entity_address
    JOIN core.address AS address ON address.id = entity_address.address_id
    WHERE entity_address.entity_type = 'organization'
      AND entity_address.entity_id = organization.id
      AND upper_inf(entity_address.valid_period)
    ORDER BY entity_address.created_at DESC, entity_address.id DESC
    LIMIT 1
) AS address_choice ON TRUE
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT data_source.filing_authority_type || ':' || data_source.filing_authority_code)
        AS filing_authority_scopes
    FROM core.entity_source AS entity_source
    JOIN core.source_record AS source_record ON source_record.id = entity_source.source_record_id
    JOIN core.data_source AS data_source ON data_source.id = source_record.data_source_id
    WHERE entity_source.entity_type = 'organization'
      AND entity_source.entity_id = organization.id
      AND data_source.domain = 'campaign_finance'
      AND data_source.filing_authority_type IS NOT NULL
) AS authority_choice ON TRUE;

DO $$
BEGIN
    IF to_regclass('core.idx_data_source_dedup') IS NOT NULL THEN
        IF to_regclass('core.idx_data_source_dedup_pre_authority') IS NOT NULL THEN
            RAISE EXCEPTION 'duplicate pre-authority data-source index';
        END IF;
        ALTER INDEX core.idx_data_source_dedup RENAME TO idx_data_source_dedup_pre_authority;
    END IF;
    IF to_regclass('cf.uq_transaction_sub_id') IS NOT NULL THEN
        IF to_regclass('cf.uq_transaction_sub_id_pre_authority') IS NOT NULL THEN
            RAISE EXCEPTION 'duplicate pre-authority transaction index';
        END IF;
        ALTER INDEX cf.uq_transaction_sub_id RENAME TO uq_transaction_sub_id_pre_authority;
    END IF;
END $$;

ALTER TABLE core.source_record SET (
    autovacuum_analyze_threshold = 250000,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_vacuum_insert_threshold = 250000,
    autovacuum_vacuum_insert_scale_factor = 0.05
);

CREATE OR REPLACE FUNCTION core.enforce_source_record_supersession_scope()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM new_rows AS source_record
        LEFT JOIN core.source_record AS successor ON successor.id = source_record.superseded_by
        WHERE source_record.superseded_by IS NOT NULL
          AND (
              successor.id IS NULL
              OR successor.data_source_id IS DISTINCT FROM source_record.data_source_id
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            CONSTRAINT = 'fk_source_record_superseded_scope',
            MESSAGE = 'source-record supersession must remain within one data source';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_source_record_supersession_scope_insert ON core.source_record;
CREATE TRIGGER trg_source_record_supersession_scope_insert
AFTER INSERT ON core.source_record
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION core.enforce_source_record_supersession_scope();
DROP TRIGGER IF EXISTS trg_source_record_supersession_scope_update ON core.source_record;
CREATE TRIGGER trg_source_record_supersession_scope_update
AFTER UPDATE ON core.source_record
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION core.enforce_source_record_supersession_scope();

ALTER TABLE cf.committee
    ADD COLUMN IF NOT EXISTS data_source_id UUID REFERENCES core.data_source(id),
    ADD COLUMN IF NOT EXISTS native_committee_id TEXT;
ALTER TABLE cf.candidate
    ADD COLUMN IF NOT EXISTS data_source_id UUID REFERENCES core.data_source(id),
    ADD COLUMN IF NOT EXISTS native_candidate_id TEXT;
ALTER TABLE cf.filing
    ADD COLUMN IF NOT EXISTS data_source_id UUID REFERENCES core.data_source(id),
    ADD COLUMN IF NOT EXISTS native_filing_id TEXT;
ALTER TABLE cf.transaction
    ADD COLUMN IF NOT EXISTS data_source_id UUID REFERENCES core.data_source(id),
    ADD COLUMN IF NOT EXISTS native_transaction_id TEXT;

DO $$
DECLARE
    target_table regclass;
    pair_constraint TEXT;
    native_constraint TEXT;
    native_column TEXT;
BEGIN
    FOR target_table, pair_constraint, native_constraint, native_column IN
        VALUES
            ('cf.committee'::regclass, 'ck_committee_authority_native_pair',
             'ck_committee_native_id_nonblank', 'native_committee_id'),
            ('cf.candidate'::regclass, 'ck_candidate_authority_native_pair',
             'ck_candidate_native_id_nonblank', 'native_candidate_id'),
            ('cf.filing'::regclass, 'ck_filing_authority_native_pair',
             'ck_filing_native_id_nonblank', 'native_filing_id'),
            ('cf.transaction'::regclass, 'ck_transaction_authority_native_pair',
             'ck_transaction_native_id_nonblank', 'native_transaction_id')
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conrelid = target_table AND conname = pair_constraint
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s ADD CONSTRAINT %I CHECK ((data_source_id IS NULL) = (%I IS NULL)) NOT VALID',
                target_table, pair_constraint, native_column
            );
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conrelid = target_table AND conname = native_constraint
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s ADD CONSTRAINT %I CHECK (%I IS NULL OR btrim(%I) <> '''') NOT VALID',
                target_table, native_constraint, native_column, native_column
            );
        END IF;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION cf.enforce_source_record_scope()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM new_rows AS owned_row
        JOIN core.source_record AS source_record ON source_record.id = owned_row.source_record_id
        WHERE owned_row.data_source_id IS NOT NULL
          AND owned_row.source_record_id IS NOT NULL
          AND source_record.data_source_id IS DISTINCT FROM owned_row.data_source_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            CONSTRAINT = 'fk_campaign_finance_source_scope',
            MESSAGE = 'campaign-finance row and source record must share one data source';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cf.enforce_filing_amendment_scope()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM new_rows AS filing
        JOIN cf.filing AS original ON original.id = filing.amended_from_filing_id
        WHERE filing.data_source_id IS NOT NULL
          AND filing.amended_from_filing_id IS NOT NULL
          AND original.data_source_id IS DISTINCT FROM filing.data_source_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            CONSTRAINT = 'fk_filing_amended_from_scope',
            MESSAGE = 'filing amendments must remain within one data source';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cf.enforce_transaction_amendment_scope()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM new_rows AS transaction
        JOIN cf.transaction AS amendment ON amendment.id = transaction.amended_by_transaction_id
        WHERE transaction.data_source_id IS NOT NULL
          AND transaction.amended_by_transaction_id IS NOT NULL
          AND amendment.data_source_id IS DISTINCT FROM transaction.data_source_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            CONSTRAINT = 'fk_transaction_amended_by_scope',
            MESSAGE = 'transaction amendments must remain within one data source';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    owner_table TEXT;
BEGIN
    FOREACH owner_table IN ARRAY ARRAY['committee', 'candidate', 'filing', 'transaction']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%1$s_source_scope_insert ON cf.%1$I', owner_table);
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_source_scope_insert '
            'AFTER INSERT ON cf.%1$I REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_source_record_scope()', owner_table
        );
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%1$s_source_scope_update ON cf.%1$I', owner_table);
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_source_scope_update '
            'AFTER UPDATE ON cf.%1$I REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_source_record_scope()', owner_table
        );
    END LOOP;
END;
$$;

DROP TRIGGER IF EXISTS trg_filing_amendment_scope_insert ON cf.filing;
CREATE TRIGGER trg_filing_amendment_scope_insert
AFTER INSERT ON cf.filing REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_filing_amendment_scope();
DROP TRIGGER IF EXISTS trg_filing_amendment_scope_update ON cf.filing;
CREATE TRIGGER trg_filing_amendment_scope_update
AFTER UPDATE ON cf.filing REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_filing_amendment_scope();

DROP TRIGGER IF EXISTS trg_transaction_amendment_scope_insert ON cf.transaction;
CREATE TRIGGER trg_transaction_amendment_scope_insert
AFTER INSERT ON cf.transaction REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_transaction_amendment_scope();
DROP TRIGGER IF EXISTS trg_transaction_amendment_scope_update ON cf.transaction;
CREATE TRIGGER trg_transaction_amendment_scope_update
AFTER UPDATE ON cf.transaction REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION cf.enforce_transaction_amendment_scope();

CREATE TABLE core.authority_scoped_identity_migration_progress (
    target_relation TEXT PRIMARY KEY,
    migration_filename TEXT NOT NULL,
    migration_sha256 TEXT NOT NULL,
    last_id UUID
);

-- civibus-phase: backfill.committee
WITH batch AS (
    SELECT committee.id, source_record.data_source_id, committee.fec_committee_id AS native_id
    FROM cf.committee AS committee
    JOIN core.source_record AS source_record ON source_record.id = committee.source_record_id
    JOIN core.authority_scoped_identity_migration_progress AS progress
      ON progress.target_relation = 'cf.committee'
    WHERE (progress.last_id IS NULL OR committee.id > progress.last_id)
      AND (committee.data_source_id IS NULL OR committee.native_committee_id IS NULL)
    ORDER BY committee.id
    LIMIT %s
    FOR UPDATE OF committee
), updated AS (
    UPDATE cf.committee AS committee
    SET data_source_id = batch.data_source_id, native_committee_id = batch.native_id
    FROM batch WHERE committee.id = batch.id
    RETURNING committee.id
), advanced AS (
    UPDATE core.authority_scoped_identity_migration_progress AS progress
    SET last_id = summary.last_id
    FROM (
        SELECT id AS last_id, count(*) OVER () AS row_count
        FROM updated
        ORDER BY id DESC
        LIMIT 1
    ) AS summary
    WHERE progress.target_relation = 'cf.committee' AND summary.row_count > 0
    RETURNING summary.row_count
)
SELECT COALESCE((SELECT row_count FROM advanced), 0);

-- civibus-phase: backfill.candidate
WITH batch AS (
    SELECT candidate.id, source_record.data_source_id, candidate.fec_candidate_id AS native_id
    FROM cf.candidate AS candidate
    JOIN core.source_record AS source_record ON source_record.id = candidate.source_record_id
    JOIN core.authority_scoped_identity_migration_progress AS progress
      ON progress.target_relation = 'cf.candidate'
    WHERE (progress.last_id IS NULL OR candidate.id > progress.last_id)
      AND (candidate.data_source_id IS NULL OR candidate.native_candidate_id IS NULL)
    ORDER BY candidate.id
    LIMIT %s
    FOR UPDATE OF candidate
), updated AS (
    UPDATE cf.candidate AS candidate
    SET data_source_id = batch.data_source_id, native_candidate_id = batch.native_id
    FROM batch WHERE candidate.id = batch.id
    RETURNING candidate.id
), advanced AS (
    UPDATE core.authority_scoped_identity_migration_progress AS progress
    SET last_id = summary.last_id
    FROM (
        SELECT id AS last_id, count(*) OVER () AS row_count
        FROM updated
        ORDER BY id DESC
        LIMIT 1
    ) AS summary
    WHERE progress.target_relation = 'cf.candidate' AND summary.row_count > 0
    RETURNING summary.row_count
)
SELECT COALESCE((SELECT row_count FROM advanced), 0);

-- civibus-phase: backfill.filing
WITH batch AS (
    SELECT filing.id, source_record.data_source_id, filing.filing_fec_id AS native_id
    FROM cf.filing AS filing
    JOIN core.source_record AS source_record ON source_record.id = filing.source_record_id
    JOIN core.authority_scoped_identity_migration_progress AS progress
      ON progress.target_relation = 'cf.filing'
    WHERE (progress.last_id IS NULL OR filing.id > progress.last_id)
      AND (filing.data_source_id IS NULL OR filing.native_filing_id IS NULL)
    ORDER BY filing.id
    LIMIT %s
    FOR UPDATE OF filing
), updated AS (
    UPDATE cf.filing AS filing
    SET data_source_id = batch.data_source_id, native_filing_id = batch.native_id
    FROM batch WHERE filing.id = batch.id
    RETURNING filing.id
), advanced AS (
    UPDATE core.authority_scoped_identity_migration_progress AS progress
    SET last_id = summary.last_id
    FROM (
        SELECT id AS last_id, count(*) OVER () AS row_count
        FROM updated
        ORDER BY id DESC
        LIMIT 1
    ) AS summary
    WHERE progress.target_relation = 'cf.filing' AND summary.row_count > 0
    RETURNING summary.row_count
)
SELECT COALESCE((SELECT row_count FROM advanced), 0);

-- civibus-phase: backfill.transaction
WITH batch AS (
    SELECT transaction.id, source_record.data_source_id,
           COALESCE(
               NULLIF(btrim(source_record.source_record_key), ''),
               transaction.sub_id::text,
               NULLIF(btrim(transaction.transaction_identifier), ''),
               transaction.id::text
           ) AS native_id
    FROM cf.transaction AS transaction
    JOIN core.source_record AS source_record ON source_record.id = transaction.source_record_id
    JOIN core.authority_scoped_identity_migration_progress AS progress
      ON progress.target_relation = 'cf.transaction'
    WHERE (progress.last_id IS NULL OR transaction.id > progress.last_id)
      AND (transaction.data_source_id IS NULL OR transaction.native_transaction_id IS NULL)
    ORDER BY transaction.id
    LIMIT %s
    FOR UPDATE OF transaction
), updated AS (
    UPDATE cf.transaction AS transaction
    SET data_source_id = batch.data_source_id, native_transaction_id = batch.native_id
    FROM batch WHERE transaction.id = batch.id
    RETURNING transaction.id
), advanced AS (
    UPDATE core.authority_scoped_identity_migration_progress AS progress
    SET last_id = summary.last_id
    FROM (
        SELECT id AS last_id, count(*) OVER () AS row_count
        FROM updated
        ORDER BY id DESC
        LIMIT 1
    ) AS summary
    WHERE progress.target_relation = 'cf.transaction' AND summary.row_count > 0
    RETURNING summary.row_count
)
SELECT COALESCE((SELECT row_count FROM advanced), 0);

-- civibus-phase: index.idx_data_source_dedup
CREATE UNIQUE INDEX CONCURRENTLY idx_data_source_dedup
    ON core.data_source (
        domain, filing_authority_type, filing_authority_code, name
    ) NULLS NOT DISTINCT;

-- civibus-phase: index.uq_committee_legacy_fec_id
CREATE UNIQUE INDEX CONCURRENTLY uq_committee_legacy_fec_id
    ON cf.committee (fec_committee_id) WHERE data_source_id IS NULL;

-- civibus-phase: index.uq_committee_authority_native_id
CREATE UNIQUE INDEX CONCURRENTLY uq_committee_authority_native_id
    ON cf.committee (data_source_id, native_committee_id) WHERE data_source_id IS NOT NULL;

-- civibus-phase: index.uq_candidate_legacy_fec_id
CREATE UNIQUE INDEX CONCURRENTLY uq_candidate_legacy_fec_id
    ON cf.candidate (fec_candidate_id) WHERE data_source_id IS NULL;

-- civibus-phase: index.uq_candidate_authority_native_id
CREATE UNIQUE INDEX CONCURRENTLY uq_candidate_authority_native_id
    ON cf.candidate (data_source_id, native_candidate_id) WHERE data_source_id IS NOT NULL;

-- civibus-phase: index.uq_filing_legacy_fec_id
CREATE UNIQUE INDEX CONCURRENTLY uq_filing_legacy_fec_id
    ON cf.filing (filing_fec_id) WHERE data_source_id IS NULL;

-- civibus-phase: index.uq_filing_authority_native_id
CREATE UNIQUE INDEX CONCURRENTLY uq_filing_authority_native_id
    ON cf.filing (data_source_id, native_filing_id) WHERE data_source_id IS NOT NULL;

-- civibus-phase: index.uq_transaction_sub_id
CREATE UNIQUE INDEX CONCURRENTLY uq_transaction_sub_id
    ON cf.transaction (sub_id) WHERE data_source_id IS NULL AND sub_id IS NOT NULL;

-- civibus-phase: index.uq_transaction_authority_native_id
CREATE UNIQUE INDEX CONCURRENTLY uq_transaction_authority_native_id
    ON cf.transaction (data_source_id, native_transaction_id) WHERE data_source_id IS NOT NULL;

-- civibus-phase: validate.ck_data_source_filing_authority_pair
ALTER TABLE core.data_source VALIDATE CONSTRAINT ck_data_source_filing_authority_pair;

-- civibus-phase: validate.ck_data_source_campaign_finance_authority
ALTER TABLE core.data_source VALIDATE CONSTRAINT ck_data_source_campaign_finance_authority;

-- civibus-phase: validate.ck_data_source_filing_authority_type
ALTER TABLE core.data_source VALIDATE CONSTRAINT ck_data_source_filing_authority_type;

-- civibus-phase: validate.ck_data_source_filing_authority_code
ALTER TABLE core.data_source VALIDATE CONSTRAINT ck_data_source_filing_authority_code;

-- civibus-phase: validate.ck_committee_authority_native_pair
ALTER TABLE cf.committee VALIDATE CONSTRAINT ck_committee_authority_native_pair;

-- civibus-phase: validate.ck_committee_native_id_nonblank
ALTER TABLE cf.committee VALIDATE CONSTRAINT ck_committee_native_id_nonblank;

-- civibus-phase: validate.ck_candidate_authority_native_pair
ALTER TABLE cf.candidate VALIDATE CONSTRAINT ck_candidate_authority_native_pair;

-- civibus-phase: validate.ck_candidate_native_id_nonblank
ALTER TABLE cf.candidate VALIDATE CONSTRAINT ck_candidate_native_id_nonblank;

-- civibus-phase: validate.ck_filing_authority_native_pair
ALTER TABLE cf.filing VALIDATE CONSTRAINT ck_filing_authority_native_pair;

-- civibus-phase: validate.ck_filing_native_id_nonblank
ALTER TABLE cf.filing VALIDATE CONSTRAINT ck_filing_native_id_nonblank;

-- civibus-phase: validate.ck_transaction_authority_native_pair
ALTER TABLE cf.transaction VALIDATE CONSTRAINT ck_transaction_authority_native_pair;

-- civibus-phase: validate.ck_transaction_native_id_nonblank
ALTER TABLE cf.transaction VALIDATE CONSTRAINT ck_transaction_native_id_nonblank;

-- civibus-phase: cutover
ALTER TABLE cf.committee DROP CONSTRAINT IF EXISTS committee_fec_committee_id_key;
ALTER TABLE cf.candidate DROP CONSTRAINT IF EXISTS candidate_fec_candidate_id_key;
ALTER TABLE cf.filing DROP CONSTRAINT IF EXISTS filing_filing_fec_id_key;

ALTER TABLE cf.committee DROP CONSTRAINT IF EXISTS fk_committee_source_scope;
ALTER TABLE cf.candidate DROP CONSTRAINT IF EXISTS fk_candidate_source_scope;
ALTER TABLE cf.filing
    DROP CONSTRAINT IF EXISTS fk_filing_source_scope,
    DROP CONSTRAINT IF EXISTS fk_filing_amended_from_scope,
    DROP CONSTRAINT IF EXISTS uq_filing_id_data_source;
ALTER TABLE cf.transaction
    DROP CONSTRAINT IF EXISTS fk_transaction_source_scope,
    DROP CONSTRAINT IF EXISTS fk_transaction_amended_by_scope,
    DROP CONSTRAINT IF EXISTS uq_transaction_id_data_source;

ALTER TABLE core.source_record
    DROP CONSTRAINT IF EXISTS fk_source_record_superseded,
    DROP CONSTRAINT IF EXISTS fk_source_record_superseded_scope,
    DROP CONSTRAINT IF EXISTS uq_source_record_id_data_source;

DROP INDEX IF EXISTS core.idx_data_source_dedup_pre_authority;
DROP INDEX IF EXISTS core.uq_source_record_id_data_source;
DROP INDEX IF EXISTS cf.uq_transaction_sub_id_pre_authority;
DROP INDEX IF EXISTS cf.uq_filing_id_data_source;
DROP INDEX IF EXISTS cf.uq_transaction_id_data_source;

DROP TABLE core.authority_scoped_identity_migration_progress;
