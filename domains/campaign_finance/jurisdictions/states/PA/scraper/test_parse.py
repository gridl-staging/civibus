from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.jurisdictions.states.PA.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.PA.scraper import parse as pa_parse
from domains.campaign_finance.jurisdictions.states.PA.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    DEBT_COLUMNS,
    EXPENDITURE_COLUMNS,
    FILING_COLUMNS,
    RECEIPT_COLUMNS,
    parse_contributions,
    parse_debts,
    parse_expenditures,
    parse_filings,
    parse_receipts,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_DEBTS_PATH = _FIXTURE_DIR / "sample_debts.csv"
_SAMPLE_RECEIPTS_PATH = _FIXTURE_DIR / "sample_receipts.csv"
_SAMPLE_FILINGS_PATH = _FIXTURE_DIR / "sample_filings.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _rows_to_csv_payload(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue()


def _build_zip_with_members(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for member_name, member_bytes in members.items():
            archive.writestr(member_name, member_bytes)


def _encode_payload(rows: list[dict[str, str]], columns: tuple[str, ...], encoding: str) -> bytes:
    return _rows_to_csv_payload(columns, rows).encode(encoding)


def test_columns_derive_from_pa_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")
    assert DEBT_COLUMNS == _load_columns_for_data_type("debts")
    assert RECEIPT_COLUMNS == _load_columns_for_data_type("receipts")
    assert FILING_COLUMNS == _load_columns_for_data_type("filings")


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad-header.csv"
    contribution_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    bad_columns = list(CONTRIBUTION_COLUMNS)
    bad_columns[0] = "wrongColumn"
    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(contribution_rows[0])

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parse_contributions(bad_header_path, year=2025))


def test_parse_normalizes_empty_strings_to_none() -> None:
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year=2025))

    assert rows
    assert rows[0]["ADDRESS1"] is None
    assert rows[0]["CONTDESC"] is None


def test_parse_skips_rows_with_missing_or_extra_fields(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.csv"
    good_row = [f"value_{index}" for index in range(len(CONTRIBUTION_COLUMNS))]
    missing_field_row = good_row[:-1]
    extra_field_row = [*good_row, "too_many_fields"]
    malformed_path.write_text(
        "\n".join(
            [
                ",".join(CONTRIBUTION_COLUMNS),
                ",".join(good_row),
                ",".join(missing_field_row),
                ",".join(extra_field_row),
                "",
            ]
        ),
        encoding="utf-8",
    )

    parser = parse_contributions(malformed_path, year=2025)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 2


def test_parse_selects_exact_member_name_for_requested_year(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:2]
    zip_path = tmp_path / "pa_contrib.zip"
    _build_zip_with_members(
        zip_path,
        {
            "contrib_2024.txt": _encode_payload([fixture_rows[0]], CONTRIBUTION_COLUMNS, "cp437"),
            "contrib_2025.txt": _encode_payload([fixture_rows[1]], CONTRIBUTION_COLUMNS, "cp437"),
        },
    )

    rows = list(parse_contributions(zip_path, year=2025))

    assert len(rows) == 1
    assert rows[0]["CONTRIBUTOR"] == fixture_rows[1]["CONTRIBUTOR"]


def test_parse_requires_exact_member_name_match(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    zip_path = tmp_path / "pa_contrib_missing_member.zip"
    _build_zip_with_members(
        zip_path,
        {
            "contrib_2024.txt": _encode_payload(fixture_rows, CONTRIBUTION_COLUMNS, "cp437"),
        },
    )

    with pytest.raises(ValueError, match="exactly one member matching"):
        list(parse_contributions(zip_path, year=2025))


def test_parse_rejects_ambiguous_member_basename_matches(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    zip_path = tmp_path / "pa_contrib_ambiguous.zip"
    payload = _encode_payload(fixture_rows, CONTRIBUTION_COLUMNS, "cp437")
    _build_zip_with_members(
        zip_path,
        {
            "contrib_2025.txt": payload,
            "nested/contrib_2025.txt": payload,
        },
    )

    with pytest.raises(ValueError, match="exactly one member matching"):
        list(parse_contributions(zip_path, year=2025))


def test_parse_rejects_oversized_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    payload = _encode_payload(fixture_rows, CONTRIBUTION_COLUMNS, "cp437")
    zip_path = tmp_path / "pa_contrib_oversized.zip"
    _build_zip_with_members(zip_path, {"contrib_2025.txt": payload})
    monkeypatch.setattr(pa_parse, "MAX_ZIP_MEMBER_BYTES", len(payload) - 1)

    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_contributions(zip_path, year=2025))


def test_parse_selects_live_redacted_naming_format(tmp_path: Path) -> None:
    """Live PA ZIPs use '{year}_{prefix}_Redacted.txt' (e.g. '2026_contrib_Redacted.txt')
    instead of the '{prefix}_{year}.txt' format found in older exports."""
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:2]
    zip_path = tmp_path / "pa_live_2026.zip"
    _build_zip_with_members(
        zip_path,
        {
            # Live format: year_prefix_Redacted.txt
            "2026_contrib_Redacted.txt": _encode_payload([fixture_rows[0]], CONTRIBUTION_COLUMNS, "cp437"),
            "2026_expense_Redacted.txt": _encode_payload([fixture_rows[1]], EXPENDITURE_COLUMNS, "cp437"),
        },
    )

    rows = list(parse_contributions(zip_path, year=2026))

    assert len(rows) == 1
    assert rows[0]["CONTRIBUTOR"] == fixture_rows[0]["CONTRIBUTOR"]


def test_parse_selects_live_redacted_expenditures(tmp_path: Path) -> None:
    """Expenditures also use the live '{year}_expense_Redacted.txt' naming."""
    fixture_rows = _read_rows(_SAMPLE_EXPENDITURES_PATH)[:1]
    zip_path = tmp_path / "pa_live_expense.zip"
    _build_zip_with_members(
        zip_path,
        {
            "2026_expense_Redacted.txt": _encode_payload(fixture_rows, EXPENDITURE_COLUMNS, "cp437"),
        },
    )

    rows = list(parse_expenditures(zip_path, year=2026))

    assert len(rows) == 1
    assert rows[0]["EXPNAME"] == fixture_rows[0]["EXPNAME"]


def test_parse_selects_live_redacted_debts(tmp_path: Path) -> None:
    """Debts also use the live '{year}_debt_Redacted.txt' naming."""
    fixture_rows = _read_rows(_SAMPLE_DEBTS_PATH)[:1]
    zip_path = tmp_path / "pa_live_debt.zip"
    _build_zip_with_members(
        zip_path,
        {
            "2026_debt_Redacted.txt": _encode_payload(fixture_rows, DEBT_COLUMNS, "utf-8"),
        },
    )

    rows = list(parse_debts(zip_path, year=2026))

    assert len(rows) == 1


def test_parse_selects_live_redacted_receipts(tmp_path: Path) -> None:
    """Receipts also use the live '{year}_receipt_Redacted.txt' naming."""
    fixture_rows = _read_rows(_SAMPLE_RECEIPTS_PATH)[:1]
    zip_path = tmp_path / "pa_live_receipt.zip"
    _build_zip_with_members(
        zip_path,
        {
            "2026_receipt_Redacted.txt": _encode_payload(fixture_rows, RECEIPT_COLUMNS, "utf-8"),
        },
    )

    rows = list(parse_receipts(zip_path, year=2026))

    assert len(rows) == 1


def test_parse_contributions_decodes_cp437_payloads(tmp_path: Path) -> None:
    row = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[0]
    zip_path = tmp_path / "pa_contrib.zip"
    _build_zip_with_members(
        zip_path,
        {
            "contrib_2025.txt": _encode_payload([row], CONTRIBUTION_COLUMNS, "cp437"),
        },
    )

    rows = list(parse_contributions(zip_path, year=2025))

    assert rows[0]["CONTRIBUTOR"] == "José Café Donor"


def test_parse_expenditures_decodes_cp437_payloads(tmp_path: Path) -> None:
    row = _read_rows(_SAMPLE_EXPENDITURES_PATH)[0]
    zip_path = tmp_path / "pa_expense.zip"
    _build_zip_with_members(
        zip_path,
        {
            "expense_2025.txt": _encode_payload([row], EXPENDITURE_COLUMNS, "cp437"),
        },
    )

    rows = list(parse_expenditures(zip_path, year=2025))

    assert rows[0]["EXPNAME"] == "Café Services LLC"


def test_parse_debts_decodes_utf8_payloads(tmp_path: Path) -> None:
    row = dict(_read_rows(_SAMPLE_DEBTS_PATH)[0])
    row["DBTNAME"] = "Renée Debt"
    zip_path = tmp_path / "pa_debt.zip"
    _build_zip_with_members(
        zip_path,
        {
            "debt_2025.txt": _encode_payload([row], DEBT_COLUMNS, "utf-8"),
        },
    )

    rows = list(parse_debts(zip_path, year=2025))

    assert rows[0]["DBTNAME"] == "Renée Debt"


def test_parse_receipts_decodes_utf8_payloads(tmp_path: Path) -> None:
    row = dict(_read_rows(_SAMPLE_RECEIPTS_PATH)[0])
    row["RECNAME"] = "Zoë Receipt Source"
    zip_path = tmp_path / "pa_receipt.zip"
    _build_zip_with_members(
        zip_path,
        {
            "receipt_2025.txt": _encode_payload([row], RECEIPT_COLUMNS, "utf-8"),
        },
    )

    rows = list(parse_receipts(zip_path, year=2025))

    assert rows[0]["RECNAME"] == "Zoë Receipt Source"


def test_parse_filings_decodes_utf8_payloads(tmp_path: Path) -> None:
    row = dict(_read_rows(_SAMPLE_FILINGS_PATH)[0])
    row["FILERNAME"] = "Comité Norte"
    zip_path = tmp_path / "pa_filer.zip"
    _build_zip_with_members(
        zip_path,
        {
            "filer_2025.txt": _encode_payload([row], FILING_COLUMNS, "utf-8"),
        },
    )

    rows = list(parse_filings(zip_path, year=2025))

    assert rows[0]["FILERNAME"] == "Comité Norte"
