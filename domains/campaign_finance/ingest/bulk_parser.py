"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_parser.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import io
import logging
from pathlib import Path
from zipfile import ZipFile

LOGGER = logging.getLogger(__name__)

ITCONT_COLUMNS: tuple[str, ...] = (
    "CMTE_ID",
    "AMNDT_IND",
    "RPT_TP",
    "TRANSACTION_PGI",
    "IMAGE_NUM",
    "TRANSACTION_TP",
    "ENTITY_TP",
    "NAME",
    "CITY",
    "STATE",
    "ZIP_CODE",
    "EMPLOYER",
    "OCCUPATION",
    "TRANSACTION_DT",
    "TRANSACTION_AMT",
    "OTHER_ID",
    "TRAN_ID",
    "FILE_NUM",
    "MEMO_CD",
    "MEMO_TEXT",
    "SUB_ID",
)

ITPAS2_COLUMNS: tuple[str, ...] = (
    "CMTE_ID",
    "AMNDT_IND",
    "RPT_TP",
    "TRANSACTION_PGI",
    "IMAGE_NUM",
    "TRANSACTION_TP",
    "ENTITY_TP",
    "NAME",
    "CITY",
    "STATE",
    "ZIP_CODE",
    "EMPLOYER",
    "OCCUPATION",
    "TRANSACTION_DT",
    "TRANSACTION_AMT",
    "OTHER_ID",
    "CAND_ID",
    "TRAN_ID",
    "FILE_NUM",
    "MEMO_CD",
    "MEMO_TEXT",
    "SUB_ID",
)

CM_COLUMNS: tuple[str, ...] = (
    "CMTE_ID",
    "CMTE_NM",
    "TRES_NM",
    "CMTE_ST1",
    "CMTE_ST2",
    "CMTE_CITY",
    "CMTE_ST",
    "CMTE_ZIP",
    "CMTE_DSGN",
    "CMTE_TP",
    "CMTE_PTY_AFFILIATION",
    "CMTE_FILING_FREQ",
    "ORG_TP",
    "CONNECTED_ORG_NM",
    "CAND_ID",
)

CN_COLUMNS: tuple[str, ...] = (
    "CAND_ID",
    "CAND_NAME",
    "CAND_PTY_AFFILIATION",
    "CAND_ELECTION_YR",
    "CAND_OFFICE_ST",
    "CAND_OFFICE",
    "CAND_OFFICE_DISTRICT",
    "CAND_ICI",
    "CAND_STATUS",
    "CAND_PCC",
    "CAND_ST1",
    "CAND_ST2",
    "CAND_CITY",
    "CAND_ST",
    "CAND_ZIP",
)

CCL_COLUMNS: tuple[str, ...] = (
    "CAND_ID",
    "CAND_ELECTION_YR",
    "FEC_ELECTION_YR",
    "CMTE_ID",
    "CMTE_TP",
    "CMTE_DSGN",
    "LINKAGE_ID",
)

COLUMNS_BY_FILE_TYPE: dict[str, tuple[str, ...]] = {
    "itcont": ITCONT_COLUMNS,
    "itpas2": ITPAS2_COLUMNS,
    "cm": CM_COLUMNS,
    "cn": CN_COLUMNS,
    "ccl": CCL_COLUMNS,
}


def parse_pipe_delimited(stream: Iterable[str], columns: tuple[str, ...]) -> Iterator[dict[str, str | None]]:
    expected_field_count = len(columns)

    for line_number, raw_line in enumerate(stream, start=1):
        parsed_line = raw_line.rstrip("\r\n")
        if not parsed_line.strip():
            continue

        fields = parsed_line.split("|")
        if fields and fields[-1] == "" and len(fields) == expected_field_count + 1:
            fields = fields[:-1]

        normalized_fields = [field.strip() for field in fields]
        if len(normalized_fields) != expected_field_count:
            LOGGER.warning(
                "Skipping row %s: expected %s fields, got %s",
                line_number,
                expected_field_count,
                len(normalized_fields),
            )
            continue

        row_values = [value or None for value in normalized_fields]
        yield dict(zip(columns, row_values, strict=True))


def _find_matching_txt_member(archive_path: Path, file_type: str) -> str:
    with ZipFile(archive_path) as archive:
        text_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]

    expected_prefix = file_type.lower()
    prefix_matches = [name for name in text_members if Path(name).name.lower().startswith(expected_prefix)]
    if prefix_matches:
        return prefix_matches[0]

    infix_matches = [name for name in text_members if expected_prefix in Path(name).name.lower()]
    if infix_matches:
        return infix_matches[0]

    raise ValueError(f"No .txt member matching file_type '{file_type}' was found in {archive_path}")


def _iter_limited(rows: Iterable[dict[str, str | None]], limit: int | None) -> Iterator[dict[str, str | None]]:
    if limit is None:
        yield from rows
        return

    for row_index, row in enumerate(rows):
        if row_index >= limit:
            break
        yield row


def read_bulk_file(path: str | Path, file_type: str, limit: int | None = None) -> Iterator[dict[str, str | None]]:
    normalized_file_type = file_type.lower()
    if normalized_file_type not in COLUMNS_BY_FILE_TYPE:
        raise ValueError(f"Unsupported file_type '{file_type}'. Expected one of {sorted(COLUMNS_BY_FILE_TYPE)}")

    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    if limit == 0:
        return

    columns = COLUMNS_BY_FILE_TYPE[normalized_file_type]
    file_path = Path(path)

    if file_path.suffix.lower() == ".zip":
        member_name = _find_matching_txt_member(file_path, normalized_file_type)
        with ZipFile(file_path) as archive:
            with archive.open(member_name, "r") as binary_stream:
                with io.TextIOWrapper(binary_stream, encoding="latin-1") as text_stream:
                    yield from _iter_limited(parse_pipe_delimited(text_stream, columns), limit)
        return

    with file_path.open("r", encoding="latin-1") as text_stream:
        yield from _iter_limited(parse_pipe_delimited(text_stream, columns), limit)
