"""Splink/DuckDB entity-resolution settings and input projections.

Owns the comparison levels, blocking rules, deterministic identifier rules, confidence
thresholds, and preprocessing SQL over the shared ER views.

Runtime status: built and tested; used by the person-spine, property-owner, and NC donor
ER paths. Federal FEC contributor tuples can now be materialized and extracted through
core.donor_er_view without writing core.person or contributor_person_id. Donor-specific
blocking, scoring, and matcher execution remain future work.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    import splink.comparison_library as cl
    import splink.comparison_level_library as cll
    from splink import SettingsCreator, block_on
except ModuleNotFoundError as import_error:
    cl = None
    cll = None
    SettingsCreator = None
    block_on = None
    _SPLINK_IMPORT_ERROR = import_error
else:
    _SPLINK_IMPORT_ERROR = None

# =============================================================================
# Confidence Thresholds
# =============================================================================

THRESHOLD_AUTO_MERGE = 0.95  # Definite match — auto-merge
THRESHOLD_PROBABLE = 0.80  # Probable match — surface to user
THRESHOLD_POSSIBLE = 0.60  # Possible match — available but flagged
# Below 0.60: not matched


def _require_splink() -> None:
    if _SPLINK_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Splink is required to build ER settings. Install with `pip install splink`."
        ) from _SPLINK_IMPORT_ERROR


PERSON_TUNING_DEFAULTS: dict[str, list[float]] = {
    "canonical_name": [0.95, 0.88, 0.80],
    "first_name": [0.95, 0.88],
    "last_name": [0.95, 0.88],
    "normalized_address": [0.92, 0.80],
    "employer": [0.92, 0.80],
    "occupation": [0.92],
}
PERSON_FIRST_NAME_DISAGREEMENT_M_PROBABILITY = 0.01
PERSON_FIRST_NAME_DISAGREEMENT_U_PROBABILITY = 0.95


def _resolved_person_tuning_overrides(overrides: dict[str, list[float]] | None) -> dict[str, list[float]]:
    resolved = deepcopy(PERSON_TUNING_DEFAULTS)
    if not overrides:
        return resolved
    for key, values in overrides.items():
        resolved[key] = list(values)
    return resolved


def _build_person_settings(
    tuning_overrides: dict[str, list[float]] | None = None,
):
    _require_splink()
    tuning = _resolved_person_tuning_overrides(tuning_overrides)
    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="id",
        blocking_rules_to_generate_predictions=[
            # Block 1: Same last name + same state
            # High recall for common patterns; state reduces comparison space
            block_on("last_name", "state"),
            # Block 2: Same zip5 + first 5 chars of last name
            # Catches name variants within same geographic area
            block_on("zip5", "last_name_prefix5"),
            # Block 3: Same street number + same zip5
            # Address-based blocking: catches name misspellings at same address
            block_on("street_number", "zip5"),
            # Block 4: Same date of birth + first 3 chars of last name
            # High precision when DOB is available
            block_on("date_of_birth", "last_name_prefix3"),
            # Block 5: Deterministic identifier match
            # Any shared identifier is an immediate block (FEC ID, voter reg, etc.)
            # Uses the identifier_key column that core.person_er_view already unnests from
            # the identifiers JSONB (see core/schema/er_views.sql) -- live, not deferred.
            block_on("identifier_key"),
        ],
        comparisons=[
            # Rare-name agreement is load-bearing for donor identity; geography, DOB,
            # employer, and occupation stay ordinary corroborating signals, not rarity priors.
            # Name comparison: Jaro-Winkler (good for typos/transpositions in names)
            cl.JaroWinklerAtThresholds(
                "canonical_name",
                score_threshold_or_thresholds=tuning["canonical_name"],
            ).configure(term_frequency_adjustments=True),
            _first_name_comparison(tuning["first_name"]),
            # Last name: exact + fuzzy
            cl.JaroWinklerAtThresholds(
                "last_name",
                score_threshold_or_thresholds=tuning["last_name"],
            ).configure(term_frequency_adjustments=True),
            # Address: token sort ratio handles word order differences
            # "123 Main St Apt 4" vs "Apt 4, 123 Main Street"
            cl.JaroWinklerAtThresholds(
                "normalized_address",
                score_threshold_or_thresholds=tuning["normalized_address"],
            ),
            # Date of birth: exact match is very strong signal
            cl.DateOfBirthComparison(
                "date_of_birth",
                input_is_string=False,
            ),
            # Zip code: exact match
            cl.ExactMatch("zip5"),
            # State: exact match
            cl.ExactMatch("state"),
            _employer_comparison(tuning["employer"]),
            # Occupation: when available, supporting signal
            cl.JaroWinklerAtThresholds(
                "occupation",
                score_threshold_or_thresholds=tuning["occupation"],
            ),
        ],
        retain_intermediate_calculation_columns=False,
        retain_matching_columns=True,
    )


def _first_name_comparison(thresholds: list[float]):
    """Build the person first-name comparison with a fixed disagreement penalty."""
    _require_splink()
    assert cl is not None
    assert cll is not None
    levels = [
        cll.NullLevel("first_name"),
        cll.ExactMatchLevel("first_name", term_frequency_adjustments=True),
        *[cll.JaroWinklerLevel("first_name", threshold) for threshold in thresholds],
        # 2026-07-28 donor audit receipt: rule 0 block_on("last_name", "state")
        # fired on 78/78 sampled false-merge edges, and
        # comparison_levels["first_name"] == 0 on 77/78. Keep maximum
        # first-name disagreement as a real model penalty, not a post-hoc filter.
        cll.ElseLevel().configure(
            m_probability=PERSON_FIRST_NAME_DISAGREEMENT_M_PROBABILITY,
            u_probability=PERSON_FIRST_NAME_DISAGREEMENT_U_PROBABILITY,
            fix_m_probability=True,
            fix_u_probability=True,
        ),
    ]
    return cl.CustomComparison(
        levels,
        output_column_name="first_name",
        comparison_description="First name disagreement veto",
    )


def _employer_comparison(thresholds: list[float]):
    """Build the trainable person employer comparison."""
    _require_splink()
    assert cl is not None
    assert cll is not None
    levels = [
        cll.NullLevel("employer"),
        cll.ExactMatchLevel("employer"),
        *[cll.JaroWinklerLevel("employer", threshold) for threshold in thresholds],
        cll.ElseLevel(),
    ]
    return cl.CustomComparison(
        levels,
        output_column_name="employer",
        comparison_description="Employer agreement",
    )


def _build_organization_settings():
    _require_splink()
    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="id",
        blocking_rules_to_generate_predictions=[
            # Block 1: Same EIN (deterministic — extremely high confidence)
            block_on("ein"),
            # Block 2: Same name + same state
            block_on("canonical_name_soundex", "registered_state"),
            # Block 3: Same registered agent name
            # Critical for LLC-piercing: same agent = likely same controller
            block_on("registered_agent_name"),
            # Block 4: Same FEC committee ID
            block_on("fec_committee_id"),
            # Block 5: Same address + first 5 chars of name
            block_on("zip5", "name_prefix5"),
        ],
        comparisons=[
            # Organization name: Jaro-Winkler + exact
            cl.JaroWinklerAtThresholds(
                "canonical_name",
                score_threshold_or_thresholds=[0.95, 0.88, 0.80],
            ),
            # EIN: exact match (deterministic, very high weight)
            cl.ExactMatch("ein"),
            # Registered state: exact match
            cl.ExactMatch("registered_state"),
            # Address: token sort
            cl.JaroWinklerAtThresholds(
                "normalized_address",
                score_threshold_or_thresholds=[0.92, 0.80],
            ),
            # Registered agent: name similarity
            cl.JaroWinklerAtThresholds(
                "registered_agent_name",
                score_threshold_or_thresholds=[0.95, 0.88],
            ),
            # Organization type: exact match
            cl.ExactMatch("org_type"),
            # Zip code: exact match
            cl.ExactMatch("zip5"),
        ],
        retain_intermediate_calculation_columns=False,
        retain_matching_columns=True,
    )


PERSON_SETTINGS = _build_person_settings() if _SPLINK_IMPORT_ERROR is None else None
ORGANIZATION_SETTINGS = _build_organization_settings() if _SPLINK_IMPORT_ERROR is None else None


# =============================================================================
# Pre-processing functions for blocking columns
# =============================================================================

# These reference views EXIST in core/schema/er_views.sql and already assemble the
# blocking columns below:
#   - core.person_er_view: canonical_name/first_name/last_name/date_of_birth, the latest
#     address (normalized_address, street_number, zip5, state), employer + occupation from
#     the identifiers JSONB, and an unnested identifier_key for block_on("identifier_key").
#     The last_name_prefix5/3 columns are derived in the preprocessing SQL below.
#   - core.organization_er_view: the organization blocking columns.
#   - core.donor_er_view: bounded, materialized federal contributor tuples for downstream
#     donor-specific matching; this module does not yet own donor matcher settings.

PERSON_PREPROCESSING_SQL = """
    SELECT
        id,
        canonical_name,
        first_name,
        last_name,
        LEFT(last_name, 5)  AS last_name_prefix5,
        LEFT(last_name, 3)  AS last_name_prefix3,
        date_of_birth,
        normalized_address,
        street_number,
        zip5,
        state,
        employer,
        occupation,
        identifier_key,      -- unnested from identifiers JSONB in the view
        filing_authority_scopes
    FROM core.person_er_view
"""

ORGANIZATION_PREPROCESSING_SQL = """
    SELECT
        id,
        canonical_name,
        SOUNDEX(canonical_name) AS canonical_name_soundex,
        LEFT(canonical_name, 5) AS name_prefix5,
        registered_state,
        normalized_address,
        zip5,
        org_type,
        identifiers->>'ein' AS ein,
        identifiers->>'fec_committee_id' AS fec_committee_id,
        registered_agent_name,
        filing_authority_scopes
    FROM core.organization_er_view
"""

DONOR_PREPROCESSING_SQL = """
    SELECT
        id,
        canonical_name,
        contributor_name_raw,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        contributor_zip,
        zip5,
        transaction_count
    FROM core.donor_er_view
"""


# =============================================================================
# Deterministic matching rules (run BEFORE Splink)
# =============================================================================
# These produce confidence=1.0 matches without needing probabilistic scoring.

# Every key these rules read MUST be one some ingest path actually writes —
# guarded by test_splink_config.py::
# test_every_deterministic_person_rule_keys_on_an_identifier_some_ingest_path_writes.
# The original fec rule keyed on 'fec_id', which nothing wrote, so the one rule
# aimed at FEC-minted duplicate persons silently matched nothing for months
# (civibus-s5q). A rule for a future key (e.g. a state voter-registration id)
# lands together with its writer, never ahead of it: the deleted
# 'voter_reg_match' rule sat equally dead because no voter ingest exists yet.
DETERMINISTIC_PERSON_RULES = [
    {
        "name": "fec_candidate_id_match",
        "description": "Overlapping FEC candidate IDs (CAND_ID)",
        # Ingest writes two shapes (see core/db_ingest.py, bulk_loader.py,
        # federal_spine_loader.py): FEC-lane persons carry a scalar
        # 'fec_candidate_id'; spine persons carry that scalar PLUS the full
        # 'fec_candidate_ids' array — a chamber switcher (House -> Senate) has
        # two CAND_IDs, and the array is a superset of the scalar whenever both
        # exist. Overlap of the per-person id SETS is therefore the correct
        # predicate: it collapses the production shadow-person class where one
        # row holds only the Senate CAND_ID and the canonical row holds both.
        "sql": """
            WITH person_fec_ids AS (
                SELECT p.id, BTRIM(ids.fec_candidate_id) AS fec_candidate_id
                FROM core.person p,
                     LATERAL jsonb_array_elements_text(
                         COALESCE(p.identifiers->'fec_candidate_ids',
                                  jsonb_build_array(p.identifiers->>'fec_candidate_id'))
                     ) AS ids(fec_candidate_id)
                WHERE NULLIF(BTRIM(ids.fec_candidate_id), '') IS NOT NULL
            ), person_authorities AS (
                SELECT entity_source.entity_id,
                       array_agg(DISTINCT data_source.filing_authority_type || ':' ||
                                data_source.filing_authority_code) AS authority_scopes
                FROM core.entity_source AS entity_source
                JOIN core.source_record AS source_record
                  ON source_record.id = entity_source.source_record_id
                JOIN core.data_source AS data_source
                  ON data_source.id = source_record.data_source_id
                WHERE entity_source.entity_type = 'person'
                  AND data_source.domain = 'campaign_finance'
                  AND data_source.filing_authority_type IS NOT NULL
                GROUP BY entity_source.entity_id
            )
            SELECT DISTINCT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM person_fec_ids a
            JOIN person_fec_ids b
              ON a.fec_candidate_id = b.fec_candidate_id
             AND a.id < b.id
            LEFT JOIN person_authorities authority_a ON authority_a.entity_id = a.id
            LEFT JOIN person_authorities authority_b ON authority_b.entity_id = b.id
            WHERE authority_a.authority_scopes IS NULL
               OR authority_b.authority_scopes IS NULL
               OR authority_a.authority_scopes && authority_b.authority_scopes
        """,
    },
    {
        "name": "bioguide_id_match",
        "description": "Same Congressional Bioguide ID",
        # bioguide_id is the spine's primary identity anchor (see
        # resolve_or_create_person_by_identifier callers); two rows sharing it
        # are the same member of Congress by construction.
        "sql": """
            WITH person_authorities AS (
                SELECT entity_source.entity_id,
                       array_agg(DISTINCT data_source.filing_authority_type || ':' ||
                                data_source.filing_authority_code) AS authority_scopes
                FROM core.entity_source AS entity_source
                JOIN core.source_record AS source_record
                  ON source_record.id = entity_source.source_record_id
                JOIN core.data_source AS data_source
                  ON data_source.id = source_record.data_source_id
                WHERE entity_source.entity_type = 'person'
                  AND data_source.domain = 'campaign_finance'
                  AND data_source.filing_authority_type IS NOT NULL
                GROUP BY entity_source.entity_id
            )
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.person a
            JOIN core.person b ON a.id < b.id
            LEFT JOIN person_authorities authority_a ON authority_a.entity_id = a.id
            LEFT JOIN person_authorities authority_b ON authority_b.entity_id = b.id
            WHERE BTRIM(a.identifiers->>'bioguide_id') = BTRIM(b.identifiers->>'bioguide_id')
              AND NULLIF(BTRIM(a.identifiers->>'bioguide_id'), '') IS NOT NULL
              AND (
                    authority_a.authority_scopes IS NULL
                 OR authority_b.authority_scopes IS NULL
                 OR authority_a.authority_scopes && authority_b.authority_scopes
              )
        """,
    },
]

DETERMINISTIC_ORG_RULES = [
    {
        "name": "fec_committee_match",
        "description": "Same FEC Committee ID",
        "sql": """
            WITH organization_authorities AS (
                SELECT entity_source.entity_id,
                       array_agg(DISTINCT data_source.filing_authority_type || ':' ||
                                data_source.filing_authority_code) AS authority_scopes
                FROM core.entity_source AS entity_source
                JOIN core.source_record AS source_record
                  ON source_record.id = entity_source.source_record_id
                JOIN core.data_source AS data_source
                  ON data_source.id = source_record.data_source_id
                WHERE entity_source.entity_type = 'organization'
                  AND data_source.domain = 'campaign_finance'
                  AND data_source.filing_authority_type IS NOT NULL
                GROUP BY entity_source.entity_id
            )
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.organization a
            JOIN core.organization b ON a.id < b.id
            LEFT JOIN organization_authorities authority_a ON authority_a.entity_id = a.id
            LEFT JOIN organization_authorities authority_b ON authority_b.entity_id = b.id
            WHERE BTRIM(a.identifiers->>'fec_committee_id') = BTRIM(b.identifiers->>'fec_committee_id')
              AND NULLIF(BTRIM(a.identifiers->>'fec_committee_id'), '') IS NOT NULL
              AND (
                    authority_a.authority_scopes IS NULL
                 OR authority_b.authority_scopes IS NULL
                 OR authority_a.authority_scopes && authority_b.authority_scopes
              )
        """,
    },
]


def get_deterministic_rules(entity_type: str) -> list[dict[str, str]]:
    if entity_type == "person":
        return DETERMINISTIC_PERSON_RULES
    if entity_type == "organization":
        return DETERMINISTIC_ORG_RULES
    raise ValueError(f"entity_type must be 'person' or 'organization', got {entity_type!r}")


def get_probabilistic_settings(entity_type: str) -> Any:
    """Return Splink settings for an entity type, or None when Splink is unavailable."""
    if entity_type == "person":
        return PERSON_SETTINGS
    if entity_type == "organization":
        return ORGANIZATION_SETTINGS
    raise ValueError(f"entity_type must be 'person' or 'organization', got {entity_type!r}")


def build_person_probabilistic_settings(
    tuning_overrides: dict[str, list[float]] | None = None,
) -> Any:
    """Build person probabilistic settings with optional threshold overrides."""
    return _build_person_settings(tuning_overrides=tuning_overrides)


def _blocking_rule_to_sql(rule: Any) -> Any:
    # Splink 4 blocking-rule objects must be passed through to training APIs.
    if hasattr(rule, "create_sql") or hasattr(rule, "get_blocking_rule"):
        return rule
    if hasattr(rule, "blocking_rule_sql"):
        return str(rule.blocking_rule_sql)
    return str(rule)


def get_blocking_rule_sqls(
    entity_type: str,
    probabilistic_settings: Any | None = None,
) -> list[Any]:
    """Return blocking rules in training-compatible form from settings."""
    settings = probabilistic_settings if probabilistic_settings is not None else get_probabilistic_settings(entity_type)
    if settings is None:
        return []

    rules = getattr(settings, "blocking_rules_to_generate_predictions", [])
    return [_blocking_rule_to_sql(rule) for rule in rules]
