from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.IL.scraper.parse import parse_contributions, parse_expenditures

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def test_parse_contributions_reads_tab_delimited_fixture() -> None:
    rows = list(parse_contributions(_FIXTURE_DIR / "Receipts_sample.txt"))

    assert len(rows) == 7
    assert rows[0]["ID"] == "236628"
    assert rows[0]["CommitteeID"] == "10353"
    assert rows[0]["D2Part"] == "2A"


def test_parse_expenditures_reads_tab_delimited_fixture() -> None:
    rows = list(parse_expenditures(_FIXTURE_DIR / "Expenditures_sample.txt"))

    assert len(rows) == 7
    assert rows[0]["ID"] == "1267"
    assert rows[0]["CommitteeID"] == "12478"
    assert rows[0]["Archived"] == "True"


def test_parse_rejects_unexpected_header(tmp_path: Path) -> None:
    broken_file = tmp_path / "broken.txt"
    broken_file.write_text("not\ta\treal\theader\n1\t2\t3\t4\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unexpected contribution header"):
        list(parse_contributions(broken_file))
