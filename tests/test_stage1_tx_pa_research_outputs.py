from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATES_ROOT = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states"

REQUIRED_SEMANTICS_SECTIONS = (
    "## Date fields",
    "## Name formats",
    "## Employer/occupation",
    "## Address format",
    "## Committee IDs",
    "## Amendment handling",
    "## Missing/null conventions",
    "## Portal Navigation",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _assert_sample_row_window(path: Path) -> None:
    lines = _read_lines(path)
    # Header + 5-10 representative rows is the stage contract.
    assert 6 <= len(lines) <= 11


def _assert_manifest(path: Path, expected_header: str, expected_line_count: int) -> None:
    lines = _read_lines(path)
    assert lines[0] == expected_header
    assert len(lines) == expected_line_count


def _manifest_rows(path: Path) -> dict[str, list[str]]:
    lines = _read_lines(path)
    header = lines[0].split("\t")
    rows: dict[str, list[str]] = {}
    for raw in lines[1:]:
        fields = raw.split("\t")
        assert len(fields) == len(header)
        rows[fields[0]] = fields
    return rows


def test_tx_stage1_research_outputs_exist_with_required_sections_and_samples() -> None:
    tx_root = STATES_ROOT / "TX"
    semantics_path = tx_root / "data_semantics.md"
    sample_rows_root = tx_root / "sample_rows"
    member_inventory_path = sample_rows_root / "member_inventory.tsv"
    encoding_check_path = sample_rows_root / "encoding_check.tsv"
    expected_samples = (
        sample_rows_root / "contributions_sample.csv",
        sample_rows_root / "expenditures_sample.csv",
        sample_rows_root / "loans_sample.csv",
    )

    assert tx_root.is_dir()
    assert semantics_path.is_file()
    assert sample_rows_root.is_dir()

    semantics_text = _read(semantics_path)
    for section in REQUIRED_SEMANTICS_SECTIONS:
        assert section in semantics_text

    assert "## Exact header rows" in semantics_text
    assert "`transaction_identifier`" in semantics_text
    assert "`source_record_key`" in semantics_text
    assert "`TX-{filerIdent}-{receivedDt[0:4]}-{data_type}`" in semantics_text
    assert "Quoting is" in semantics_text

    for sample_path in expected_samples:
        assert sample_path.is_file()
        _assert_sample_row_window(sample_path)
        assert _read_lines(sample_path)[0] in semantics_text

    assert member_inventory_path.is_file()
    assert encoding_check_path.is_file()
    _assert_manifest(member_inventory_path, "filename\trows\tdelimiter\theader", 136)
    _assert_manifest(encoding_check_path, "filename\tutf8_valid", 136)


def test_pa_stage1_research_outputs_exist_with_required_sections_and_samples() -> None:
    pa_root = STATES_ROOT / "PA"
    semantics_path = pa_root / "data_semantics.md"
    sample_rows_root = pa_root / "sample_rows"
    member_inventory_path = sample_rows_root / "member_inventory.tsv"
    encoding_check_path = sample_rows_root / "encoding_check.tsv"
    expected_samples = (
        sample_rows_root / "contrib_sample.csv",
        sample_rows_root / "expense_sample.csv",
        sample_rows_root / "debt_sample.csv",
        sample_rows_root / "filer_sample.csv",
        sample_rows_root / "receipt_sample.csv",
    )

    assert pa_root.is_dir()
    assert semantics_path.is_file()
    assert sample_rows_root.is_dir()

    semantics_text = _read(semantics_path)
    for section in REQUIRED_SEMANTICS_SECTIONS:
        assert section in semantics_text

    assert "## Exact header rows" in semantics_text
    assert "`transaction_identifier`" in semantics_text
    assert "`source_record_key`" in semantics_text
    assert "`PA-{FILERID}-{SubmittedDate[0:4]}-{data_type}`" in semantics_text
    assert "Quoting is" in semantics_text
    assert "implementation must derive each detail row's `amendment_indicator`" in semantics_text
    assert "should stay an explicit deferred linkage issue rather than defaulting to `N`" in semantics_text

    for sample_path in expected_samples:
        assert sample_path.is_file()
        _assert_sample_row_window(sample_path)
        assert _read_lines(sample_path)[0] in semantics_text

    assert member_inventory_path.is_file()
    assert encoding_check_path.is_file()
    _assert_manifest(member_inventory_path, "filename\trows\tdelimiter\theader", 6)
    _assert_manifest(
        encoding_check_path,
        "filename\tutf8_valid\tdetected_encoding\tbyte_evidence_hex\tdecode_recommendation",
        6,
    )

    encoding_rows = _manifest_rows(encoding_check_path)
    assert encoding_rows["contrib_2025.txt"][1:] == ["no", "cp437_or_cp850", "0x82,0xA0,0xFF", "decode_cp437"]
    assert encoding_rows["expense_2025.txt"][1:] == ["no", "cp437_or_cp850", "0x82", "decode_cp437"]
    assert encoding_rows["debt_2025.txt"][1:] == ["yes", "utf-8", "none", "decode_utf8"]
    assert encoding_rows["filer_2025.txt"][1:] == ["yes", "utf-8", "none", "decode_utf8"]
    assert encoding_rows["receipt_2025.txt"][1:] == ["yes", "utf-8", "none", "decode_utf8"]
