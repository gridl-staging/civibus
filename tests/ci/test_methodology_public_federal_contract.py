"""DB-free drift guards for static methodology disclosure copy."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
    RECEIPT_TYPE_PREFIX,
    contribution_insights_transaction_where_sql,
)
from api.health_content import _DONOR_ROLLUP_FRESHNESS_MAX_AGE, _FEC_BULK_FRESHNESS_MAX_AGE
from api.queries.campaign_finance import (
    CONTRIBUTION_INSIGHTS_CYCLES,
    _DONOR_SEARCH_KEY_COLUMNS,
    _DONOR_SEARCH_ROLLUP_MAX_AGE,
    _PERSON_TOP_DONORS_SELECT_SQL,
    public_top_donors_identity_resolution_status,
)
from api.routes.public_federal import (
    _PUBLIC_EMPLOYER_INDUSTRY_CLASSIFIED_COUNT,
    _PUBLIC_EMPLOYER_INDUSTRY_UNKNOWN_COUNT,
    _employer_industry_benchmark,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG_PATH = REPO_ROOT / "web/src/lib/config/app.ts"
_PERCENTAGE_RE = re.compile(r"(?<![\d.])(?P<value>\d+(?:\.\d+)?)%(?!\d)")


def _extract_methodology_config_text(config_source: str) -> str:
    match = re.search(
        r"^  methodology: \{\n(?P<body>.*?)^  \}",
        config_source,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "APP_SHELL.methodology must remain the static methodology copy owner"
    return match.group("body")


def _methodology_config_text() -> str:
    return _extract_methodology_config_text(APP_CONFIG_PATH.read_text(encoding="utf-8"))


def _contains_bounded_value(text: str, value: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text) is not None


def _contains_standalone_year(text: str, year: int) -> bool:
    return re.search(rf"(?<![\d-]){year}(?![\d-])", text) is not None


def _public_top_donor_grouping_columns(select_sql: str) -> tuple[str, ...]:
    match = re.search(r"\bGROUP BY\s+(?P<grouping>.*?)\s+ORDER BY\b", select_sql, flags=re.DOTALL)
    assert match is not None, "public top-donors SQL must retain an inspectable GROUP BY clause"
    columns = re.findall(r"\b(?:contributor_[a-z_]+|normalized_zip5|[a-z_]+_identity_id)\b", match.group("grouping"))
    return tuple(dict.fromkeys(columns))


def _public_top_donor_copy_errors(
    methodology_text: str,
    grouping_columns: tuple[str, ...],
    identity_status: str,
) -> list[str]:
    normalized_text = re.sub(r"\s+", " ", methodology_text)
    sentence = next(
        (
            candidate
            for candidate in re.split(r"(?<=[.!?])\s+", normalized_text)
            if "public official top-contributor" in candidate.lower()
        ),
        None,
    )
    if sentence is None:
        return ["public official top-contributor disclosure"]

    errors = []
    identity_phrase = rf"\b{re.escape(identity_status)}\s+raw identities\b"
    if re.search(identity_phrase, sentence, flags=re.IGNORECASE) is None:
        errors.append(f"{identity_status} raw-identity status")
    disclosed_columns = tuple(
        dict.fromkeys(
            re.findall(
                r"\b(?:contributor_[a-z_]+|normalized_zip5|[a-z_]+_identity_id)\b",
                sentence,
            )
        )
    )
    if disclosed_columns != grouping_columns:
        errors.append(f"grouping columns {grouping_columns!r}; disclosed {disclosed_columns!r}")
    return errors


def _compact_timedelta(value: timedelta) -> str:
    total_seconds = int(value.total_seconds())
    assert value == timedelta(seconds=total_seconds) and total_seconds >= 0
    days, remainder = divmod(total_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    parts = [
        f"{amount}{suffix}" for amount, suffix in ((days, "d"), (hours, "h"), (minutes, "m"), (seconds, "s")) if amount
    ]
    return "".join(parts) or "0s"


def _freshness_role_bounds() -> tuple[tuple[str, str], ...]:
    return (
        ("FEC bulk freshness health", _compact_timedelta(_FEC_BULK_FRESHNESS_MAX_AGE)),
        ("donor-rollup health", _compact_timedelta(_DONOR_ROLLUP_FRESHNESS_MAX_AGE)),
        ("donor-search serving freshness", _compact_timedelta(_DONOR_SEARCH_ROLLUP_MAX_AGE)),
    )


def _freshness_copy_errors(
    methodology_text: str,
    role_bounds: tuple[tuple[str, str], ...],
) -> list[str]:
    normalized_text = re.sub(r"\s+", " ", methodology_text)
    errors = []
    for role, bound in role_bounds:
        role_pattern = re.escape(role).replace(r"\ ", r"\s+")
        bound_pattern = rf"(?<![A-Za-z0-9_]){re.escape(bound)}(?![A-Za-z0-9_])"
        if (
            re.search(
                rf"{role_pattern}[^.!?]*?\bbounded\s+at\s+{bound_pattern}",
                normalized_text,
                flags=re.IGNORECASE,
            )
            is None
        ):
            errors.append(f"{role} at {bound}")
    return errors


def _percentage_matches_benchmark(methodology_text: str, expected: Decimal) -> bool:
    for match in _PERCENTAGE_RE.finditer(methodology_text):
        displayed_text = match.group("value")
        displayed = Decimal(displayed_text)
        decimal_places = len(displayed_text.partition(".")[2])
        display_quantum = Decimal(1).scaleb(-decimal_places)
        if displayed == expected.quantize(display_quantum):
            return True
    return False


def _employer_industry_copy_errors(methodology_text: str) -> list[str]:
    benchmark = _employer_industry_benchmark()
    normalized_text = methodology_text.replace(",", "")
    errors = [
        label
        for label, value in (
            ("classified count", str(_PUBLIC_EMPLOYER_INDUSTRY_CLASSIFIED_COUNT)),
            ("unknown count", str(_PUBLIC_EMPLOYER_INDUSTRY_UNKNOWN_COUNT)),
        )
        if not _contains_bounded_value(normalized_text, value)
    ]
    if not _percentage_matches_benchmark(normalized_text, benchmark.sampled_coverage_percentage):
        errors.append("API-derived percentage")
    return errors


def test_methodology_extraction_excludes_later_app_shell_siblings() -> None:
    config_source = """export const APP_SHELL = {
  methodology: {
    heading: "Methodology"
  },
  glossary: {
    body: "837 classified, 13,487 unknown, 5.843340%"
  }
} as const;
"""

    methodology_text = _extract_methodology_config_text(config_source)

    assert "glossary" not in methodology_text
    assert _employer_industry_copy_errors(methodology_text) == [
        "classified count",
        "unknown count",
        "API-derived percentage",
    ]


def test_employer_industry_percentage_uses_copy_precision() -> None:
    expected = _employer_industry_benchmark().sampled_coverage_percentage

    assert _percentage_matches_benchmark("Coverage is 5.8%.", expected)
    assert _percentage_matches_benchmark("Coverage is 5.84334%.", expected)
    assert not _percentage_matches_benchmark("Coverage is 5.9%.", expected)


def test_public_top_donor_copy_guard_uses_sql_grouping_columns() -> None:
    grouping_columns = _public_top_donor_grouping_columns(_PERSON_TOP_DONORS_SELECT_SQL)
    copy = (
        "Public official top-contributor rows remain unresolved raw identities grouped only by "
        "contributor_name_raw, contributor_city, and contributor_state."
    )

    assert grouping_columns == ("contributor_name_raw", "contributor_city", "contributor_state")
    assert _public_top_donor_copy_errors(copy, grouping_columns, "unresolved") == []
    assert _public_top_donor_copy_errors(copy, grouping_columns, "resolved") == ["resolved raw-identity status"]
    changed_select_sql = _PERSON_TOP_DONORS_SELECT_SQL.replace(
        "GROUP BY BTRIM(contributor_name_raw), contributor_city, contributor_state",
        "GROUP BY BTRIM(contributor_name_raw), contributor_city, contributor_employer",
    )
    changed_grouping_columns = _public_top_donor_grouping_columns(changed_select_sql)
    assert changed_grouping_columns == ("contributor_name_raw", "contributor_city", "contributor_employer")
    assert _public_top_donor_copy_errors(
        copy,
        changed_grouping_columns,
        "unresolved",
    ) == [
        "grouping columns ('contributor_name_raw', 'contributor_city', 'contributor_employer'); "
        "disclosed ('contributor_name_raw', 'contributor_city', 'contributor_state')"
    ]


def test_freshness_copy_guard_associates_each_bound_with_its_role() -> None:
    role_bounds = (
        ("FEC bulk freshness health", "7d"),
        ("donor-rollup health", "7d6h"),
        ("donor-search serving freshness", "8d"),
    )
    copy = (
        "FEC bulk freshness health is bounded at 7d. "
        "Donor-rollup health is bounded at 7d6h. "
        "Donor-search serving freshness is bounded at 8d."
    )

    assert _freshness_role_bounds() == role_bounds
    assert _freshness_copy_errors(copy, role_bounds) == []
    swapped_copy = (
        "FEC bulk freshness health is bounded at 8d. "
        "Donor-rollup health is bounded at 7d6h. "
        "Donor-search serving freshness is bounded at 7d."
    )
    assert _freshness_copy_errors(swapped_copy, role_bounds) == [
        "FEC bulk freshness health at 7d",
        "donor-search serving freshness at 8d",
    ]
    colliding_backend_bounds = (
        ("FEC bulk freshness health", "8d"),
        role_bounds[1],
        role_bounds[2],
    )
    assert _freshness_copy_errors(copy, colliding_backend_bounds) == ["FEC bulk freshness health at 8d"]


def test_methodology_copy_matches_public_employer_industry_benchmark() -> None:
    benchmark = _employer_industry_benchmark()
    assert benchmark.classified_count == _PUBLIC_EMPLOYER_INDUSTRY_CLASSIFIED_COUNT
    assert benchmark.unknown_count == _PUBLIC_EMPLOYER_INDUSTRY_UNKNOWN_COUNT

    errors = _employer_industry_copy_errors(_methodology_config_text())

    assert errors == [], (
        "APP_SHELL.methodology must disclose the classified count, unknown count, "
        f"and API-derived percentage at its chosen display precision; missing or stale {errors}"
    )


def test_methodology_copy_matches_schedule_a_and_donor_grouping_owners() -> None:
    methodology_text = _methodology_config_text()
    transaction_where_sql = contribution_insights_transaction_where_sql()

    # Prove that the user-facing phrases below still describe the backend owner.
    assert f"transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'" in transaction_where_sql
    assert "contributor_entity_type = 'IND'" in transaction_where_sql
    assert "is_memo = FALSE" in transaction_where_sql
    assert "amendment_indicator != 'T'" in transaction_where_sql
    assert "superseded_by IS NOT NULL" in NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL

    missing_values = [
        value
        for value in (
            CONTRIBUTION_INSIGHTS_MIN_DATE.isoformat(),
            f"transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%'",
            "contributor_entity_type = 'IND'",
            "no memo rows",
            "no terminated amendments",
            "no superseded source records",
            *_DONOR_SEARCH_KEY_COLUMNS,
        )
        if not _contains_bounded_value(methodology_text, value)
    ]
    missing_cycles = [
        cycle for cycle in CONTRIBUTION_INSIGHTS_CYCLES if not _contains_standalone_year(methodology_text, cycle)
    ]

    assert missing_cycles == [], f"APP_SHELL.methodology is missing supported Schedule A cycles: {missing_cycles}"
    assert missing_values == [], f"APP_SHELL.methodology is missing backend-owned disclosure values: {missing_values}"


def test_methodology_copy_matches_public_top_donor_owner() -> None:
    grouping_columns = _public_top_donor_grouping_columns(_PERSON_TOP_DONORS_SELECT_SQL)
    identity_status = public_top_donors_identity_resolution_status()
    errors = _public_top_donor_copy_errors(_methodology_config_text(), grouping_columns, identity_status)

    assert errors == [], f"APP_SHELL.methodology is stale against the public top-donors query owner: {errors}"


def test_methodology_copy_matches_freshness_owners() -> None:
    methodology_text = _methodology_config_text()
    errors = _freshness_copy_errors(methodology_text, _freshness_role_bounds())

    assert errors == [], f"APP_SHELL.methodology is missing backend-owned freshness role/bound pairs: {errors}"
