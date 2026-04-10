from __future__ import annotations

from pathlib import Path


_OH_DIR = Path(__file__).resolve().parents[1]
_SCRAPER_DIR = _OH_DIR / "scraper"


def test_stage5_required_scraper_files_exist() -> None:
    required_scraper_files = (
        "extract.py",
        "load.py",
        "test_extract.py",
        "test_load.py",
    )

    for file_name in required_scraper_files:
        assert (_SCRAPER_DIR / file_name).is_file()


def test_stage5_public_extract_and_load_symbols_importable() -> None:
    from domains.campaign_finance.jurisdictions.states.OH.scraper.extract import (  # noqa: PLC0415
        extract_oh_contribution,
        extract_oh_expenditure,
    )
    from domains.campaign_finance.jurisdictions.states.OH.scraper.load import (  # noqa: PLC0415
        LoadResult,
        ensure_oh_data_source,
        load_oh_contributions,
        load_oh_expenditures,
    )

    assert callable(extract_oh_contribution)
    assert callable(extract_oh_expenditure)
    assert callable(ensure_oh_data_source)
    assert callable(load_oh_contributions)
    assert callable(load_oh_expenditures)
    assert LoadResult.__name__ == "LoadResult"


def test_stage5_extract_and_load_use_config_driven_column_lookups() -> None:
    extract_source = (_SCRAPER_DIR / "extract.py").read_text(encoding="utf-8")
    load_source = (_SCRAPER_DIR / "load.py").read_text(encoding="utf-8")

    assert "_load_column_for_semantic_path(" in extract_source
    assert "_load_column_for_semantic_path(" in load_source

    mapped_columns = (
        "COM_NAME",
        "MASTER_KEY",
        "REPORT_DESCRIPTION",
        "RPT_YEAR",
        "REPORT_KEY",
        "SHORT_DESCRIPTION",
        "FIRST_NAME",
        "MIDDLE_NAME",
        "LAST_NAME",
        "SUFFIX_NAME",
        "NON_INDIVIDUAL",
        "PAC_REG_NO",
        "ADDRESS",
        "CITY",
        "STATE",
        "ZIP",
        "FILE_DATE",
        "EXPEND_DATE",
        "AMOUNT",
        "EVENT_DATE",
        "EMP_OCCUPATION",
    )
    for column in mapped_columns:
        assert f'row["{column}"]' not in extract_source
        assert f"row['{column}']" not in extract_source
        assert f'row["{column}"]' not in load_source
        assert f"row['{column}']" not in load_source
