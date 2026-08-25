"""Known-answer contracts for projecting and replacing contribution-limit rules.

This is the red-phase owner for the missing YAML-to-row loader. Config validation
semantics stay in ``test_contribution_limit_rules.py``; this module starts with valid,
specimen-derived configs and pins only projection and persistence behavior.
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions._config_specimens import CO_CONFIG_PATH, SF_CONFIG_PATH
from domains.campaign_finance.jurisdictions._contribution_rule_seeds import (
    CONTRIBUTION_RULES_OMITTED,
    known_nonnumeric_rule,
    numeric_rule,
    unknown_rule,
    write_seeded_config_to_root,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)


CITY_FIPS = "test-6dfbca4a-municipality"
STATE_FIPS = "test-6dfbca4a-state"
EXCLUDED_FIPS = "test-6dfbca4a-excluded"

CITY_RULES = [
    numeric_rule(
        limit_amount=750,
        office_level="mayor",
        election_type="general",
        effective_date="2025-01-01",
        sunset_date="2026-12-31",
        source_citation="S.F. Campaign & Governmental Conduct Code § 1.114",
        local_override_allowed=True,
        note="Indexed amount for the fixture period.",
        metadata=[
            {
                "description": "Candidate self-funding is outside this cap.",
                "source_citation": "S.F. Campaign & Governmental Conduct Code § 1.114(b)",
            }
        ],
    ),
    unknown_rule(
        donor_type="union",
        recipient_type="party_committee",
        office_level="city_council",
        election_type="special",
        research_observed_date="2026-08-23",
        source_citation="Synthetic municipal research gap observed 2026-08-23",
        note="Municipal union-to-party rule has not been researched.",
    ),
]

STATE_RULES = [
    known_nonnumeric_rule(
        "prohibited",
        donor_type="corporation",
        recipient_type="candidate_committee",
        office_level="governor",
        election_type="primary",
        effective_date="2024-07-01",
        source_citation="Colo. Const. art. XXVIII, § 3(4)",
        note="Direct corporate contributions are prohibited.",
        metadata=[
            {
                "description": "The prohibition applies to direct treasury contributions.",
                "source_citation": "Colo. Const. art. XXVIII, § 3(4)(a)",
            }
        ],
    )
]

EXPECTED_CITY_ROWS = [
    {
        "jurisdiction_fips": CITY_FIPS,
        "donor_type": "individual",
        "recipient_type": "candidate_committee",
        "office_level": "mayor",
        "election_type": "general",
        "limit_status": "numeric",
        "limit_amount": 750,
        "limit_basis": "per_election",
        "source_citation": "S.F. Campaign & Governmental Conduct Code § 1.114",
        "effective_date": "2025-01-01",
        "sunset_date": "2026-12-31",
        "research_observed_date": None,
        "local_override_allowed": True,
        "note": "Indexed amount for the fixture period.",
        "metadata": [
            {
                "description": "Candidate self-funding is outside this cap.",
                "source_citation": "S.F. Campaign & Governmental Conduct Code § 1.114(b)",
            }
        ],
    },
    {
        "jurisdiction_fips": CITY_FIPS,
        "donor_type": "union",
        "recipient_type": "party_committee",
        "office_level": "city_council",
        "election_type": "special",
        "limit_status": "unknown",
        "limit_amount": None,
        "limit_basis": None,
        "source_citation": "Synthetic municipal research gap observed 2026-08-23",
        "effective_date": None,
        "sunset_date": None,
        "research_observed_date": "2026-08-23",
        "local_override_allowed": False,
        "note": "Municipal union-to-party rule has not been researched.",
        "metadata": [],
    },
]

EXPECTED_STATE_ROWS = [
    {
        "jurisdiction_fips": STATE_FIPS,
        "donor_type": "corporation",
        "recipient_type": "candidate_committee",
        "office_level": "governor",
        "election_type": "primary",
        "limit_status": "prohibited",
        "limit_amount": None,
        "limit_basis": None,
        "source_citation": "Colo. Const. art. XXVIII, § 3(4)",
        "effective_date": "2024-07-01",
        "sunset_date": None,
        "research_observed_date": None,
        "local_override_allowed": False,
        "note": "Direct corporate contributions are prohibited.",
        "metadata": [
            {
                "description": "The prohibition applies to direct treasury contributions.",
                "source_citation": "Colo. Const. art. XXVIII, § 3(4)(a)",
            }
        ],
    }
]

ROW_COLUMNS = (
    "jurisdiction_fips",
    "donor_type",
    "recipient_type",
    "office_level",
    "election_type",
    "limit_status",
    "limit_amount",
    "limit_basis",
    "source_citation",
    "effective_date",
    "sunset_date",
    "research_observed_date",
    "local_override_allowed",
    "note",
    "metadata",
)


def _project_contribution_limit_rule_rows(config: JurisdictionConfig) -> list[dict[str, object]]:
    """Import lazily so valid fixture construction runs before the intentional red."""
    from domains.campaign_finance.jurisdictions.contribution_limit_rule_loader import (
        project_contribution_limit_rule_rows,
    )

    return project_contribution_limit_rule_rows(config)


def _replace_contribution_limit_rules(
    connection: psycopg.Connection,
    config_paths: list[Path],
) -> None:
    from domains.campaign_finance.jurisdictions.contribution_limit_rule_loader import (
        replace_contribution_limit_rules,
    )

    replace_contribution_limit_rules(connection, config_paths)


@pytest.fixture
def known_answer_config_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Seed one city and one state through the same specimen-copy helper."""
    config_root = tmp_path / "jurisdictions"
    city_path = write_seeded_config_to_root(
        config_root,
        base_path=SF_CONFIG_PATH,
        jurisdiction_fips=CITY_FIPS,
        rules=CITY_RULES,
        directory_name="path_fragment_06075",
    )
    state_path = write_seeded_config_to_root(
        config_root,
        base_path=CO_CONFIG_PATH,
        jurisdiction_fips=STATE_FIPS,
        rules=STATE_RULES,
        directory_name="path_fragment_08",
    )
    return config_root, city_path, state_path


def test_projects_exact_rows_for_numeric_nonnumeric_and_unknown_rules(
    known_answer_config_root: tuple[Path, Path, Path],
) -> None:
    _, city_path, state_path = known_answer_config_root

    city_rows = _project_contribution_limit_rule_rows(load_jurisdiction_config(city_path))
    state_rows = _project_contribution_limit_rule_rows(load_jurisdiction_config(state_path))

    assert len(city_rows) + len(state_rows) == 3
    assert city_rows == EXPECTED_CITY_ROWS
    assert state_rows == EXPECTED_STATE_ROWS


@pytest.mark.parametrize(
    "rules",
    [CONTRIBUTION_RULES_OMITTED, None],
    ids=["omitted", "explicit-null"],
)
def test_omitted_and_null_rule_lists_project_zero_rows(
    tmp_path: Path,
    rules: object,
    loader_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = write_seeded_config_to_root(
        tmp_path,
        base_path=SF_CONFIG_PATH,
        jurisdiction_fips="test-6dfbca4a-zero",
        rules=rules,
        directory_name="misleading_fixture_fips_06075",
    )
    config = load_jurisdiction_config(config_path)

    assert _project_contribution_limit_rule_rows(config) == []

    def _fail_if_connection_opened(**_overrides: object) -> None:
        raise AssertionError("an empty replacement must not open a database connection")

    monkeypatch.setattr(loader_module, "get_connection", _fail_if_connection_opened)
    with pytest.raises(SystemExit) as empty_replacement_exit:
        loader_module.main(["--config-root", str(tmp_path)])

    assert empty_replacement_exit.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1] == (
        "pytest: error: refusing to replace contribution-limit rules with an empty projection"
    )
    with pytest.raises(ValueError, match="refusing to replace contribution-limit rules with an empty projection"):
        loader_module.replace_contribution_limit_rules(_RowcountSentinelConnection(), [config_path])


def test_discovers_both_regions_and_uses_only_enclosing_config_fips(
    known_answer_config_root: tuple[Path, Path, Path],
) -> None:
    config_root, city_path, state_path = known_answer_config_root

    discovered_paths = discover_jurisdiction_configs(config_root)
    configs = [load_jurisdiction_config(path) for path in discovered_paths]
    rows = [row for config in configs for row in _project_contribution_limit_rule_rows(config)]

    assert discovered_paths == sorted([city_path.resolve(), state_path.resolve()])
    assert {config.jurisdiction.fips for config in configs} == {CITY_FIPS, STATE_FIPS}
    assert len(rows) == 3
    assert rows == [*EXPECTED_CITY_ROWS, *EXPECTED_STATE_ROWS]
    assert {row["jurisdiction_fips"] for row in rows} == {CITY_FIPS, STATE_FIPS}
    assert not {"06075", "08", "path_fragment_06075", "path_fragment_08"} & {row["jurisdiction_fips"] for row in rows}


class _FakeConnection:
    """Context-managed stand-in so CLI writing mode is provable without PostgreSQL."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> _FakeConnection:
        self.entered = True
        return self

    def __exit__(self, *exception_details: object) -> bool:
        self.exited = True
        return False


class _FakeTransaction:
    """Minimal transaction context for replacement-summary unit tests."""

    def __enter__(self) -> _FakeTransaction:
        return self

    def __exit__(self, *exception_details: object) -> bool:
        return False


class _FakeCursor:
    """Cursor stub that exposes a caller-controlled rowcount after work."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exception_details: object) -> bool:
        return False

    def execute(self, *_arguments: object) -> None:
        return None

    def executemany(self, *_arguments: object) -> None:
        return None


class _RowcountSentinelConnection:
    """Connection stub whose insert cursor mimics psycopg's unknown rowcount."""

    def __init__(self) -> None:
        self._cursor_rowcounts = [2, -1]

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._cursor_rowcounts.pop(0))


@pytest.fixture
def loader_module() -> ModuleType:
    """Import the loader module itself so its CLI seams can be monkeypatched."""
    return importlib.import_module("domains.campaign_finance.jurisdictions.contribution_limit_rule_loader")


def test_dry_run_reports_discovered_and_projected_counts_without_opening_postgres(
    loader_module: ModuleType,
    known_answer_config_root: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_root, _, _ = known_answer_config_root

    def _fail_if_connection_opened(**_overrides: object) -> None:
        raise AssertionError("dry-run must not open a database connection")

    monkeypatch.setattr(loader_module, "get_connection", _fail_if_connection_opened)

    exit_code = loader_module.main(["--config-root", str(config_root), "--dry-run"])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines() == [
        "Discovered configs: 2",
        "Projected contribution-limit rules: 3",
    ]

    missing_config_root = config_root / "missing"
    for mode_arguments in (["--dry-run"], []):
        with pytest.raises(SystemExit) as missing_root_exit:
            loader_module.main(["--config-root", str(missing_config_root), *mode_arguments])

        assert missing_root_exit.value.code == 2
        assert capsys.readouterr().err.splitlines()[-1] == (
            f"pytest: error: no jurisdiction config.yaml files found under {missing_config_root}"
        )


def test_writing_mode_prints_replacement_summary_without_recomputing_counts(
    loader_module: ModuleType,
    known_answer_config_root: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_root, city_path, state_path = known_answer_config_root
    fake_connection = _FakeConnection()
    replacement_calls: list[tuple[object, list[Path]]] = []
    # Counts the CLI could not derive from the two seeded configs on its own, so
    # printing them proves the CLI formats the shared summary instead of recounting.
    stub_summary = loader_module.ContributionLimitRuleReplacementSummary(
        included_jurisdiction_count=2,
        deleted_row_count=5,
        inserted_row_count=3,
    )

    def _record_replacement(connection: object, config_paths: list[Path]) -> object:
        replacement_calls.append((connection, list(config_paths)))
        return stub_summary

    monkeypatch.setattr(loader_module, "get_connection", lambda **_overrides: fake_connection)
    monkeypatch.setattr(loader_module, "replace_contribution_limit_rules", _record_replacement)

    exit_code = loader_module.main(["--config-root", str(config_root)])

    assert exit_code == 0
    assert replacement_calls == [(fake_connection, sorted([city_path.resolve(), state_path.resolve()]))]
    assert fake_connection.entered and fake_connection.exited
    assert capsys.readouterr().out.splitlines() == [
        "Included jurisdictions: 2",
        "Deleted contribution-limit rules: 5",
        "Inserted contribution-limit rules: 3",
    ]


def test_replace_summary_falls_back_to_projected_count_for_unknown_insert_rowcount(
    loader_module: ModuleType,
    known_answer_config_root: tuple[Path, Path, Path],
) -> None:
    _, city_path, state_path = known_answer_config_root
    fake_connection = _RowcountSentinelConnection()

    summary = loader_module.replace_contribution_limit_rules(
        fake_connection,
        sorted([city_path.resolve(), state_path.resolve()]),
    )

    assert summary.included_jurisdiction_count == 2
    assert summary.deleted_row_count == 2
    assert summary.inserted_row_count == 3


def _normalize_database_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {key: value.isoformat() if isinstance(value, date) else value for key, value in row.items()}
        )
    return normalized_rows


def _select_synthetic_rows(connection: psycopg.Connection) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT {", ".join(ROW_COLUMNS)}
            FROM cf.contribution_limit_rules
            WHERE jurisdiction_fips = ANY(%s)
            ORDER BY jurisdiction_fips, source_citation
            """,
            ([CITY_FIPS, STATE_FIPS, EXCLUDED_FIPS],),
        )
        return _normalize_database_rows(list(cursor.fetchall()))


def _insert_stale_rule(connection: psycopg.Connection, jurisdiction_fips: str, citation: str) -> None:
    connection.execute(
        """
        INSERT INTO cf.contribution_limit_rules (
            jurisdiction_fips,
            donor_type,
            recipient_type,
            limit_status,
            source_citation,
            effective_date,
            note
        )
        VALUES (%s, 'pac', 'candidate_committee', 'prohibited', %s, '2020-01-01', %s)
        """,
        (jurisdiction_fips, citation, f"stale sentinel for {jurisdiction_fips}"),
    )


@pytest.mark.integration
def test_replace_is_idempotent_and_scoped_to_discovered_fips(
    db_conn: psycopg.Connection,
    known_answer_config_root: tuple[Path, Path, Path],
) -> None:
    config_root, _, _ = known_answer_config_root
    config_paths = discover_jurisdiction_configs(config_root)
    _insert_stale_rule(db_conn, CITY_FIPS, "included stale row must be deleted")
    _insert_stale_rule(db_conn, EXCLUDED_FIPS, "excluded row must survive")

    _replace_contribution_limit_rules(db_conn, config_paths)
    rows_after_first_run = _select_synthetic_rows(db_conn)
    _replace_contribution_limit_rules(db_conn, config_paths)
    rows_after_second_run = _select_synthetic_rows(db_conn)

    excluded_row = {
        "jurisdiction_fips": EXCLUDED_FIPS,
        "donor_type": "pac",
        "recipient_type": "candidate_committee",
        "office_level": None,
        "election_type": None,
        "limit_status": "prohibited",
        "limit_amount": None,
        "limit_basis": None,
        "source_citation": "excluded row must survive",
        "effective_date": "2020-01-01",
        "sunset_date": None,
        "research_observed_date": None,
        "local_override_allowed": False,
        "note": f"stale sentinel for {EXCLUDED_FIPS}",
        "metadata": [],
    }
    expected_rows = sorted(
        [*EXPECTED_CITY_ROWS, *EXPECTED_STATE_ROWS, excluded_row],
        key=lambda row: (row["jurisdiction_fips"], row["source_citation"]),
    )

    assert rows_after_first_run == expected_rows
    assert rows_after_second_run == expected_rows
    assert all(row["source_citation"] != "included stale row must be deleted" for row in rows_after_second_run)
