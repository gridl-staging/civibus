
from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on
except ModuleNotFoundError as import_error:
    cl = None
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
            # NOTE: Requires person_er_view to unnest identifiers JSONB into individual
            # rows with an identifier_key column. View assembly is deferred to Stage 2.
            block_on("identifier_key"),
        ],
        comparisons=[
            # Name comparison: Jaro-Winkler (good for typos/transpositions in names)
            cl.JaroWinklerAtThresholds(
                "canonical_name",
                score_threshold_or_thresholds=tuning["canonical_name"],
            ),
            # First name: handles nicknames, abbreviations
            cl.JaroWinklerAtThresholds(
                "first_name",
                score_threshold_or_thresholds=tuning["first_name"],
            ),
            # Last name: exact + fuzzy
            cl.JaroWinklerAtThresholds(
                "last_name",
                score_threshold_or_thresholds=tuning["last_name"],
            ),
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
            # Employer: when available, strong signal
            cl.JaroWinklerAtThresholds(
                "employer",
                score_threshold_or_thresholds=tuning["employer"],
            ),
            # Occupation: when available, supporting signal
            cl.JaroWinklerAtThresholds(
                "occupation",
                score_threshold_or_thresholds=tuning["occupation"],
            ),
        ],
        retain_intermediate_calculation_columns=False,
        retain_matching_columns=True,
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

# These reference views (person_er_view, organization_er_view) don't exist yet.
# They'll join core tables + domain data to surface the columns needed for blocking.
# Stage 2 work includes:
#   - View assembly (which tables/domains contribute which columns)
#   - Identifier unnesting: identifiers JSONB must be unnested into rows with
#     (identifier_key, identifier_value) columns for block_on("identifier_key") to work
#   - Cross-domain link_type configuration
#
# The SQL below is illustrative — column availability depends on view implementation.

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
        identifier_key      -- unnested from identifiers JSONB in the view
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
        registered_agent_name
    FROM core.organization_er_view
"""


# =============================================================================
# Deterministic matching rules (run BEFORE Splink)
# =============================================================================
# These produce confidence=1.0 matches without needing probabilistic scoring.

DETERMINISTIC_PERSON_RULES = [
    {
        "name": "fec_id_match",
        "description": "Same FEC individual contributor ID",
        "sql": """
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.person a, core.person b
            WHERE a.id < b.id
              AND BTRIM(a.identifiers->>'fec_id') = BTRIM(b.identifiers->>'fec_id')
              AND NULLIF(BTRIM(a.identifiers->>'fec_id'), '') IS NOT NULL
        """,
    },
    {
        "name": "voter_reg_match",
        "description": "Same state voter registration ID",
        "sql": """
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.person a, core.person b
            WHERE a.id < b.id
              AND BTRIM(a.identifiers->>'voter_reg_id') = BTRIM(b.identifiers->>'voter_reg_id')
              AND NULLIF(BTRIM(a.identifiers->>'voter_reg_id'), '') IS NOT NULL
        """,
    },
]

DETERMINISTIC_ORG_RULES = [
    {
        "name": "ein_match",
        "description": "Same EIN (Employer Identification Number)",
        "sql": """
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.organization a, core.organization b
            WHERE a.id < b.id
              AND BTRIM(a.identifiers->>'ein') = BTRIM(b.identifiers->>'ein')
              AND NULLIF(BTRIM(a.identifiers->>'ein'), '') IS NOT NULL
        """,
    },
    {
        "name": "fec_committee_match",
        "description": "Same FEC Committee ID",
        "sql": """
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.organization a, core.organization b
            WHERE a.id < b.id
              AND BTRIM(a.identifiers->>'fec_committee_id') = BTRIM(b.identifiers->>'fec_committee_id')
              AND NULLIF(BTRIM(a.identifiers->>'fec_committee_id'), '') IS NOT NULL
        """,
    },
    {
        "name": "sos_id_match",
        "description": "Same Secretary of State registration ID",
        "sql": """
            SELECT a.id AS entity_id_a, b.id AS entity_id_b, 1.0 AS confidence
            FROM core.organization a, core.organization b
            WHERE a.id < b.id
              AND BTRIM(a.identifiers->>'sos_id') = BTRIM(b.identifiers->>'sos_id')
              AND NULLIF(BTRIM(a.identifiers->>'sos_id'), '') IS NOT NULL
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
