from __future__ import annotations

from collections import Counter
from pathlib import Path

from _test_helpers import markdown_table_under_heading, read


REPO_ROOT = Path(__file__).resolve().parents[6]
UNIVERSE_DOC_PATH = REPO_ROOT / "docs" / "research" / "nc_office_universe_2026_04_24.md"
ARTIFACT_ROOT = REPO_ROOT / "docs" / "research" / "artifacts" / "2026_04_24_nc_office_universe"

REQUIRED_COLUMNS = [
    "office_class",
    "fixture_slug",
    "scope_decision",
    "expected_owner",
    "artifact_paths",
]

EXPECTED_OWNERS = {
    "domains/campaign_finance/jurisdictions/states/NC/config.yaml",
    "domains/campaign_finance/jurisdictions/states/NC/README.md",
    "domains/campaign_finance/jurisdictions/states/NC/tests/test_stage6_regressions.py",
}

REQUIRED_VALIDATION_COMMANDS = (
    "pytest domains/campaign_finance/jurisdictions/states/NC/tests/test_office_universe_inventory.py -q",
    "pytest domains/campaign_finance/jurisdictions/states/NC/tests/test_stage6_regressions.py -q",
)

EVIDENCE_TOKEN_BY_FIXTURE_SLUG = {
    "nc_state_house": "ADAMS FOR NC HOUSE",
    "nc_state_senate": "GALE ADCOCK FOR NC SENATE",
    "nc_county": "JOHN ADCOCK FOR COUNTY COMMISSIONER",
    "nc_municipal": "JASON MERRILL FOR CARRBORO TOWN COUNCIL",
    "nc_judicial": "RICHARD N ADAMS FOR DIST CT JUDGE",
}


def test_universe_table_contract_has_required_columns_unique_keys_and_allowed_owners() -> None:
    headers, rows = markdown_table_under_heading(read(UNIVERSE_DOC_PATH), "Universe Table")

    assert headers == REQUIRED_COLUMNS
    assert rows, "Universe Table must include at least one office-class row"

    office_classes = [row["office_class"] for row in rows]
    fixture_slugs = [row["fixture_slug"] for row in rows]
    duplicate_office_classes = [key for key, count in Counter(office_classes).items() if count > 1]
    duplicate_fixture_slugs = [key for key, count in Counter(fixture_slugs).items() if count > 1]

    assert not duplicate_office_classes, f"duplicate office_class values: {duplicate_office_classes}"
    assert not duplicate_fixture_slugs, f"duplicate fixture_slug values: {duplicate_fixture_slugs}"

    for row in rows:
        assert row["expected_owner"] in EXPECTED_OWNERS

        artifact_paths = [path.strip() for path in row["artifact_paths"].split(";") if path.strip()]
        assert artifact_paths, f"artifact_paths must include at least one retained path: {row}"
        for artifact_path in artifact_paths:
            assert artifact_path.startswith("docs/research/artifacts/2026_04_24_nc_office_universe/")
            assert (REPO_ROOT / artifact_path).exists()
            assert (REPO_ROOT / artifact_path).is_file()

        expected_token = EVIDENCE_TOKEN_BY_FIXTURE_SLUG.get(row["fixture_slug"])
        if expected_token is not None:
            assert _any_artifact_contains_token(artifact_paths, expected_token), (
                f"fixture_slug={row['fixture_slug']} requires retained evidence token {expected_token!r}"
            )

    command_log_text = read(ARTIFACT_ROOT / "command_log_2026_04_25.txt")
    for command in REQUIRED_VALIDATION_COMMANDS:
        assert command in command_log_text, f"missing required validation command record: {command}"


def _any_artifact_contains_token(artifact_paths: list[str], token: str) -> bool:
    for artifact_path in artifact_paths:
        artifact_text = (REPO_ROOT / artifact_path).read_text(encoding="utf-8", errors="ignore")
        if token in artifact_text:
            return True
    return False
