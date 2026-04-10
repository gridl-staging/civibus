-- ER input views for Splink preprocessing SQL.
-- Migration order: after entity_resolution.sql, before domain tables that may consume views.

CREATE SCHEMA IF NOT EXISTS core;

CREATE OR REPLACE VIEW core.person_er_view AS
SELECT
    p.id,
    p.canonical_name,
    p.first_name,
    p.last_name,
    p.date_of_birth,
    address_choice.normalized_address,
    address_choice.street_number,
    address_choice.zip5,
    address_choice.state,
    p.identifiers->>'employer' AS employer,
    p.identifiers->>'occupation' AS occupation,
    identifier_choice.identifier_key
FROM core.person p
LEFT JOIN LATERAL (
    SELECT
        a.normalized_address,
        a.street_number,
        a.zip5,
        a.state
    FROM core.entity_address ea
    JOIN core.address a ON a.id = ea.address_id
    WHERE ea.entity_type = 'person'
      AND ea.entity_id = p.id
      AND upper_inf(ea.valid_period)
    ORDER BY ea.created_at DESC, ea.id DESC
    LIMIT 1
) AS address_choice ON TRUE
LEFT JOIN LATERAL (
    SELECT
        identifier_item.key || ':' || BTRIM(identifier_item.value) AS identifier_key
    FROM jsonb_each_text(p.identifiers) AS identifier_item(key, value)
    WHERE identifier_item.key NOT IN ('employer', 'occupation', 'occupation_comments', 'llc_name')
      AND NULLIF(BTRIM(identifier_item.value), '') IS NOT NULL
) AS identifier_choice ON TRUE;

CREATE OR REPLACE VIEW core.organization_er_view AS
SELECT
    o.id,
    o.canonical_name,
    o.registered_state,
    address_choice.normalized_address,
    address_choice.zip5,
    o.org_type,
    o.identifiers,
    o.identifiers->>'registered_agent_name' AS registered_agent_name
FROM core.organization o
LEFT JOIN LATERAL (
    SELECT
        a.normalized_address,
        a.zip5
    FROM core.entity_address ea
    JOIN core.address a ON a.id = ea.address_id
    WHERE ea.entity_type = 'organization'
      AND ea.entity_id = o.id
      AND upper_inf(ea.valid_period)
    ORDER BY ea.created_at DESC, ea.id DESC
    LIMIT 1
) AS address_choice ON TRUE;
