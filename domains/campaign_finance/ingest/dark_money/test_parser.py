"""Tests for IRS 527 pipe-delimited parser with record-type dispatch."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from domains.campaign_finance.ingest.dark_money import parser as dark_money_parser
from domains.campaign_finance.ingest.dark_money.parser import (
    IRS_527_COLUMNS_BY_RECORD_TYPE,
    _recency_cutoff_date,
    iter_irs_527_rows,
    read_irs_527_records,
)
from domains.campaign_finance.types import (
    Contribution527,
    Expenditure527,
    Filing8872,
    PoliticalOrganization527,
)

FIXTURE_ZIP = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bulk" / "irs_527_sample.zip"


def _fixture_txt_path() -> Path:
    """Extract fixture txt to a temp location for direct parser testing."""
    from domains.campaign_finance.ingest.dark_money.download import extract_irs_527_txt
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    return extract_irs_527_txt(FIXTURE_ZIP, tmp)


# ==========================================================================
# Parser shape tests: iter_irs_527_rows dispatch and normalization
# ==========================================================================


class TestIrs527ColumnsByRecordType:
    def test_type_1_has_43_columns(self):
        assert len(IRS_527_COLUMNS_BY_RECORD_TYPE["1"]) == 43

    def test_type_2_has_48_columns(self):
        assert len(IRS_527_COLUMNS_BY_RECORD_TYPE["2"]) == 48

    def test_type_a_has_16_columns(self):
        assert len(IRS_527_COLUMNS_BY_RECORD_TYPE["A"]) == 16

    def test_type_b_has_16_columns(self):
        assert len(IRS_527_COLUMNS_BY_RECORD_TYPE["B"]) == 16

    def test_only_modeled_record_types_present(self):
        assert set(IRS_527_COLUMNS_BY_RECORD_TYPE.keys()) == {"1", "2", "A", "B"}


class TestIterIrs527Rows:
    def test_dispatches_type_1_with_correct_columns(self):
        line = "1|8871|100000001|1|0|0|12-3456789|TEST ORG" + "|" * 36 + "\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 1
        record_type, row = rows[0]
        assert record_type == "1"
        assert row["form_type"] == "8871"
        assert row["form_id_number"] == "100000001"
        assert row["ein"] == "12-3456789"
        assert row["organization_name"] == "TEST ORG"

    def test_dispatches_type_2_with_correct_columns(self):
        fields = ["2", "8872", "200000001", "01012025", "06302025"]
        fields.extend([""] * (49 - len(fields)))
        line = "|".join(fields) + "|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 1
        record_type, row = rows[0]
        assert record_type == "2"
        assert row["form_type"] == "8872"
        assert row["period_begin_date"] == "01012025"

    def test_dispatches_type_a_with_correct_columns(self):
        line = "A|200000001|A00001|TEST ORG|12-3456789|JANE DONOR|100 LN||PORTLAND|OR|97201||ACME|5000.00|ENGINEER|10000.00|03152025|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 1
        record_type, row = rows[0]
        assert record_type == "A"
        assert row["form_id_number"] == "200000001"
        assert row["contributor_name"] == "JANE DONOR"
        assert row["contribution_amount"] == "5000.00"

    def test_dispatches_type_b_with_correct_columns(self):
        line = "B|200000001|B00001|TEST ORG|12-3456789|AD AGENCY|200 BLVD||NEW YORK|NY|10001||MEDIA LLC|25000.00|CONSULTING|04012025|TV ADS|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 1
        record_type, row = rows[0]
        assert record_type == "B"
        assert row["reciepient_name"] == "AD AGENCY"
        assert row["expenditure_amount"] == "25000.00"
        assert row["expenditure_purpose"] == "TV ADS"

    def test_skips_non_modeled_record_types(self):
        lines = "H|20260329|0817|001|\nD|100|D001|ORG|12-3456789|NAME|TITLE|ADDR||CITY|ST|ZIP||\nR|100|R001|ORG|12-3456789|NAME|REL|ADDR||CITY|ST|ZIP||\nE|100|E001|EAIN001|CA|\nF|20260329|0817|4|\n"
        rows = list(iter_irs_527_rows(StringIO(lines)))
        assert len(rows) == 0

    def test_normalizes_empty_fields_to_none(self):
        fields = ["1", "8871", "100000001", "", "", "", "12-3456789", "ORG"]
        fields.extend([""] * (44 - len(fields)))
        line = "|".join(fields) + "|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        _, row = rows[0]
        assert row["initial_report_indicator"] is None
        assert row["amended_report_indicator"] is None

    def test_strips_whitespace_from_fields(self):
        fields = ["1", " 8871 ", "100000001", "1", "0", "0", " 12-3456789 ", " PADDED ORG "]
        fields.extend([""] * (44 - len(fields)))
        line = "|".join(fields) + "|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        _, row = rows[0]
        assert row["form_type"] == "8871"
        assert row["ein"] == "12-3456789"
        assert row["organization_name"] == "PADDED ORG"

    def test_handles_pipe_terminated_rows(self):
        """Rows end with trailing pipe — should not create an extra empty field."""
        line = "A|200000001|A00001|ORG|12-3456789|DONOR|ADDR||CITY|ST|ZIP||EMP|1000.00|OCC|2000.00|01012025|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 1

    def test_warns_and_skips_malformed_rows(self, caplog: pytest.LogCaptureFixture):
        line = "1|only|three|fields|\n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 0
        assert "Skipping" in caplog.text

    def test_skips_blank_lines(self):
        line = "\n\n   \n"
        rows = list(iter_irs_527_rows(StringIO(line)))
        assert len(rows) == 0

    def test_processes_fixture_file(self):
        txt_path = _fixture_txt_path()
        with txt_path.open(encoding="latin-1") as f:
            rows = list(iter_irs_527_rows(f))
        record_types = [rt for rt, _ in rows]
        assert record_types.count("1") == 2
        assert record_types.count("2") == 2
        assert record_types.count("A") == 2
        assert record_types.count("B") == 2
        assert "H" not in record_types
        assert "D" not in record_types


# ==========================================================================
# Typed-output tests: read_irs_527_records emits Pydantic models
# ==========================================================================


class TestReadIrs527RecordsTypedOutput:
    def test_emits_political_organization_from_type_1(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        orgs = [r for r in records if isinstance(r, PoliticalOrganization527)]
        assert len(orgs) == 2
        org = orgs[0]
        assert org.form_type == "8871"
        assert org.form_id_number == "100000001"
        assert org.ein == "12-3456789"
        assert org.name == "AMERICANS FOR GOOD THINGS"
        assert org.mailing_address_city == "WASHINGTON"
        assert org.established_date == date(2020, 1, 15)

    def test_emits_filing_from_type_2(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        filings = [r for r in records if isinstance(r, Filing8872)]
        assert len(filings) >= 1  # at least the recent one (filter may drop old)
        filing = filings[0]
        assert filing.form_type == "8872"
        assert filing.ein == "12-3456789"
        assert filing.period_begin_date == date(2025, 1, 1)
        assert filing.period_end_date == date(2025, 6, 30)

    def test_emits_contribution_from_type_a(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        contribs = [r for r in records if isinstance(r, Contribution527)]
        assert len(contribs) >= 1
        c = contribs[0]
        assert c.contributor_name == "JANE DONOR"
        assert c.amount == Decimal("5000.00")
        assert c.contribution_date == date(2025, 3, 15)
        assert c.aggregate_ytd == Decimal("10000.00")

    def test_emits_expenditure_from_type_b(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        expenditures = [r for r in records if isinstance(r, Expenditure527)]
        assert len(expenditures) >= 1
        e = expenditures[0]
        assert e.recipient_name == "AD AGENCY INC"
        assert e.amount == Decimal("25000.00")
        assert e.expenditure_date == date(2025, 4, 1)
        assert e.purpose == "TELEVISION ADVERTISING"

    def test_coerces_date_fields(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        org = next(r for r in records if isinstance(r, PoliticalOrganization527) and r.ein == "12-3456789")
        assert isinstance(org.established_date, date)
        assert org.established_date == date(2020, 1, 15)

    def test_coerces_decimal_fields(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        filing = next(r for r in records if isinstance(r, Filing8872) and r.form_id_number == "200000001")
        assert isinstance(filing.total_sched_a, Decimal)
        assert filing.total_sched_a == Decimal("50000.00")

    def test_normalizes_irs_reciepient_typo_to_recipient(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        exp = next(r for r in records if isinstance(r, Expenditure527) and r.sched_b_id == "B00001")
        assert exp.recipient_name == "AD AGENCY INC"
        assert exp.recipient_address_1 == "200 MEDIA BLVD"
        assert exp.recipient_address_city == "NEW YORK"
        assert exp.recipient_address_state == "NY"

    def test_indicator_fields_parse_to_bool(self):
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        org = next(r for r in records if isinstance(r, PoliticalOrganization527) and r.ein == "12-3456789")
        assert org.initial_report_indicator is True
        assert org.amended_report_indicator is False
        assert org.exempt_8872_indicator is True
        assert org.exempt_990_indicator is False


# ==========================================================================
# 5-year recency filter tests
# ==========================================================================


class TestReadIrs527RecordsRecencyFilter:
    def test_filters_old_type_2_filings(self):
        """Type 2 records from before cutoff year are excluded."""
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        filings = [r for r in records if isinstance(r, Filing8872)]
        # Only the 2025 filing should survive; 2020 filing should be filtered
        assert all(f.period_begin_date.year >= 2022 for f in filings)
        assert len(filings) == 1

    def test_filters_old_type_a_contributions(self):
        """Type A contributions from before cutoff year are excluded."""
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        contribs = [r for r in records if isinstance(r, Contribution527)]
        assert all(c.contribution_date.year >= 2022 for c in contribs)
        assert len(contribs) == 1

    def test_filters_old_type_b_expenditures(self):
        """Type B expenditures from before cutoff year are excluded."""
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        expenditures = [r for r in records if isinstance(r, Expenditure527)]
        assert all(e.expenditure_date.year >= 2022 for e in expenditures)
        assert len(expenditures) == 1

    def test_keeps_type_1_orgs_regardless_of_date(self):
        """Type 1 organization records are undated — always kept for join support."""
        txt = _fixture_txt_path()
        records = list(read_irs_527_records(txt))
        orgs = [r for r in records if isinstance(r, PoliticalOrganization527)]
        assert len(orgs) == 2

    def test_cutoff_is_current_year_minus_4(self):
        """For 2026, cutoff should be 2022-01-01."""
        txt = _fixture_txt_path()
        # Patch the current year to verify dynamic cutoff
        with patch("domains.campaign_finance.ingest.dark_money.parser._recency_cutoff_date") as mock_cutoff:
            mock_cutoff.return_value = date(2022, 1, 1)
            records = list(read_irs_527_records(txt))
        filings = [r for r in records if isinstance(r, Filing8872)]
        # 2020 filing (period_begin_date 2020-01-01) should be filtered
        assert all(f.period_begin_date >= date(2022, 1, 1) for f in filings)

    def test_recency_cutoff_date_computes_current_year_minus_4(self, monkeypatch: pytest.MonkeyPatch):
        class FixedDate(date):
            @classmethod
            def today(cls) -> "FixedDate":
                return cls(2026, 4, 10)

        monkeypatch.setattr(dark_money_parser, "date", FixedDate)

        assert _recency_cutoff_date() == date(2022, 1, 1)


# ==========================================================================
# Nullable date cutoff regression tests
# ==========================================================================


class TestReadIrs527NullableDateCutoff:
    """Records with null dates must be included, not crash on cutoff comparison."""

    @staticmethod
    def _write_test_file(tmp_path: Path, lines: list[str]) -> Path:
        p = tmp_path / "test_null_dates.txt"
        p.write_text("".join(lines), encoding="latin-1")
        return p

    def test_type_a_null_contribution_date_included(self, tmp_path: Path):
        fields = [
            "A",
            "300000001",
            "A99999",
            "TEST ORG",
            "12-3456789",
            "TEST DONOR",
            "100 MAIN",
            "",
            "CITY",
            "ST",
            "12345",
            "",
            "ACME",
            "1000.00",
            "ENG",
            "2000.00",
            "",
        ]
        line = "|".join(fields) + "|\n"
        txt = self._write_test_file(tmp_path, [line])
        records = list(read_irs_527_records(txt))
        contribs = [r for r in records if isinstance(r, Contribution527)]
        assert len(contribs) == 1
        assert contribs[0].contribution_date is None

    def test_type_b_null_expenditure_date_and_purpose_included(self, tmp_path: Path):
        fields = [
            "B",
            "300000001",
            "B99999",
            "TEST ORG",
            "12-3456789",
            "VENDOR",
            "200 ELM",
            "",
            "TOWN",
            "CA",
            "90210",
            "",
            "MEDIA",
            "5000.00",
            "CONSULT",
            "",
            "",
        ]
        line = "|".join(fields) + "|\n"
        txt = self._write_test_file(tmp_path, [line])
        records = list(read_irs_527_records(txt))
        expenditures = [r for r in records if isinstance(r, Expenditure527)]
        assert len(expenditures) == 1
        assert expenditures[0].expenditure_date is None
        assert expenditures[0].purpose is None

    def test_type_2_null_period_dates_included(self, tmp_path: Path):
        fields = ["2", "8872", "300000001", "", ""]
        fields.extend(["0", "0", "0", "0"])
        fields.append("TEST ORG")
        fields.append("12-3456789")
        fields.extend([""] * (49 - len(fields)))
        line = "|".join(fields) + "|\n"
        txt = self._write_test_file(tmp_path, [line])
        records = list(read_irs_527_records(txt))
        filings = [r for r in records if isinstance(r, Filing8872)]
        assert len(filings) == 1
        assert filings[0].period_begin_date is None
