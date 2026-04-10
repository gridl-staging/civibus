from __future__ import annotations

from domains.campaign_finance.coverage.seed_registry import (
    build_fec_registry_row,
    build_seed_registry,
    derive_state_registry_rows,
)


def _rows_by_code() -> dict[str, object]:
    return {row.jurisdiction_code: row for row in derive_state_registry_rows()}


def test_derive_state_registry_rows_aggregation_and_runner_wiring() -> None:
    rows_by_code = _rows_by_code()
    # 22 state packages: AL, CA, CO, FL, GA, IL, IN, KY, LA, MA, MN, NC, NE, NJ, NY, OH, OR, PA, TX, VA, WA, WI
    assert len(rows_by_code) == 22

    assert rows_by_code["CA"].best_update_frequency == "daily"
    assert rows_by_code["CA"].source_count == 2

    assert rows_by_code["IL"].best_update_frequency == "continuous"
    assert rows_by_code["IL"].source_count == 2
    assert rows_by_code["IL"].covers_sub_jurisdictions is True
    assert rows_by_code["IL"].runner_wired is True

    assert rows_by_code["WA"].best_update_frequency == "daily"
    assert rows_by_code["WA"].source_count == 5

    assert rows_by_code["MN"].covers_sub_jurisdictions is False

    # Runner wiring: all states except OH are in _SUPPORTED_STATE_CODES
    assert rows_by_code["CA"].runner_wired is True
    assert rows_by_code["OH"].runner_wired is False
    assert rows_by_code["IN"].runner_wired is True
    assert rows_by_code["WI"].runner_wired is True
    assert rows_by_code["WI"].best_update_frequency == "daily"
    assert rows_by_code["WI"].source_count == 3
    assert rows_by_code["NJ"].runner_wired is True
    assert rows_by_code["NJ"].source_count == 2
    assert rows_by_code["NJ"].best_update_frequency == "quarterly"
    assert rows_by_code["NJ"].covers_sub_jurisdictions is True

    assert rows_by_code["OH"].best_last_verified_working is None


def test_build_fec_registry_row_uses_manual_contract_values() -> None:
    row = build_fec_registry_row()

    assert row.jurisdiction_code == "FEC"
    assert row.name == "Federal Election Commission"
    assert row.jurisdiction_type == "federal"
    assert row.best_update_frequency == "continuous"
    assert row.best_last_verified_working is None
    assert row.covers_sub_jurisdictions is False
    assert row.source_count == 3
    assert row.source_names == ["FEC Schedule A API", "FEC Bulk Data", "FEC Schedule E/IE"]
    assert row.runner_wired is True
    assert row.tier is None
    assert row.evidence_summary is None
    assert row.operational_reason is None
    assert row.next_action is None
    assert row.evidence_date is None


def test_build_seed_registry_includes_fec_plus_fourteen_states() -> None:
    registry = build_seed_registry()
    codes = [row.jurisdiction_code for row in registry.rows]

    assert codes[0] == "FEC"
    # FEC + 22 states = 23 total rows
    assert len(registry.rows) == 23
    assert set(codes[1:]) == {
        "AL",
        "CA",
        "CO",
        "FL",
        "GA",
        "IL",
        "IN",
        "KY",
        "LA",
        "MA",
        "MN",
        "NC",
        "NE",
        "NJ",
        "NY",
        "OH",
        "OR",
        "PA",
        "TX",
        "VA",
        "WA",
        "WI",
    }
