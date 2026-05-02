
from __future__ import annotations

import csv
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


YAML_KEY_LINE = re.compile(r"^\s*(?:-\s+)?([A-Za-z_][A-Za-z0-9_]*):")


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"required file missing: {path}")
    return path.read_text(encoding="utf-8")


def assert_files_exist(*paths: Path) -> None:
    for path in paths:
        read(path)


def csv_headers(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as fixture_file:
        return next(csv.reader(fixture_file))


def _source_record_count(conn: psycopg.Connection, data_source_id) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record
            WHERE data_source_id = %s
            """,
            (data_source_id,),
        )
        return cursor.fetchone()["count"]


def _delete_entity_references(cursor: psycopg.Cursor, jurisdiction: str) -> None:
    """Delete entity_source and entity_address rows linked to a jurisdiction's source records."""
    source_record_subquery = """
        SELECT sr.id
        FROM core.source_record sr
        JOIN core.data_source ds ON ds.id = sr.data_source_id
        WHERE ds.jurisdiction = %s
    """
    cursor.execute(
        f"DELETE FROM core.entity_source WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM core.entity_address WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )


def _delete_civic_and_contact_records(cursor: psycopg.Cursor, jurisdiction: str) -> None:
    """Delete canonical civic/contact rows linked to a jurisdiction's source records."""
    source_record_subquery = """
        SELECT sr.id
        FROM core.source_record sr
        JOIN core.data_source ds ON ds.id = sr.data_source_id
        WHERE ds.jurisdiction = %s
    """
    cursor.execute(
        f"DELETE FROM core.contact_point WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM civic.officeholding WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM civic.candidacy WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM civic.contest WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM civic.electoral_division WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )
    cursor.execute(
        f"DELETE FROM civic.office WHERE source_record_id IN ({source_record_subquery})",
        (jurisdiction,),
    )


def _delete_cf_records(cursor: psycopg.Cursor, jurisdiction: str, state_code: str) -> None:
    """Delete CF transactions, filings, candidates, committees, and their linkage rows for a state."""
    cursor.execute(
        """
        DELETE FROM cf.transaction
        WHERE source_record_id IN (
            SELECT sr.id
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.jurisdiction = %s
        )
           OR filing_id IN (
            SELECT f.id
            FROM cf.filing f
            JOIN cf.committee c ON c.id = f.committee_id
            WHERE c.state = %s
        )
           OR committee_id IN (
            SELECT id FROM cf.committee WHERE state = %s
        )
        """,
        (jurisdiction, state_code, state_code),
    )
    cursor.execute(
        """
        DELETE FROM cf.filing
        WHERE source_record_id IN (
            SELECT sr.id
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.jurisdiction = %s
        )
           OR committee_id IN (
            SELECT id FROM cf.committee WHERE state = %s
        )
        """,
        (jurisdiction, state_code),
    )
    # Candidate-linked records: links, residual transactions/filings, then candidates themselves.
    state_candidates_subquery = """
        SELECT id FROM cf.candidate
        WHERE principal_committee_id IN (SELECT id FROM cf.committee WHERE state = %s)
    """
    cursor.execute(
        f"""
        DELETE FROM cf.candidate_committee_link
        WHERE committee_id IN (SELECT id FROM cf.committee WHERE state = %s)
           OR candidate_id IN ({state_candidates_subquery})
        """,
        (state_code, state_code),
    )
    cursor.execute(
        f"DELETE FROM cf.transaction WHERE recipient_candidate_id IN ({state_candidates_subquery})",
        (state_code,),
    )
    cursor.execute(
        f"DELETE FROM cf.filing WHERE candidate_id IN ({state_candidates_subquery})",
        (state_code,),
    )
    cursor.execute(
        "DELETE FROM cf.candidate WHERE principal_committee_id IN (SELECT id FROM cf.committee WHERE state = %s)",
        (state_code,),
    )
    cursor.execute("DELETE FROM cf.committee WHERE state = %s", (state_code,))


def clear_state_loader_records(conn: psycopg.Connection, jurisdiction: str, state_code: str) -> None:
    with conn.cursor() as cursor:
        _delete_entity_references(cursor, jurisdiction)
        _delete_civic_and_contact_records(cursor, jurisdiction)
        _delete_cf_records(cursor, jurisdiction, state_code)
        cursor.execute(
            """
            DELETE FROM core.source_record
            WHERE data_source_id IN (
                SELECT id FROM core.data_source WHERE jurisdiction = %s
            )
            """,
            (jurisdiction,),
        )


def extract_named_block(text: str, key: str) -> str:
    lines = text.splitlines()
    header_pattern = re.compile(rf"^(?P<indent>\s*){re.escape(key)}:")

    for index, line in enumerate(lines):
        match = header_pattern.match(line)
        if match is None:
            continue

        block_indent = len(match.group("indent"))
        block_lines = [line]
        for candidate in lines[index + 1 :]:
            candidate_indent = len(candidate) - len(candidate.lstrip(" "))
            if candidate.strip() and candidate_indent <= block_indent:
                break
            block_lines.append(candidate)
        return "\n".join(block_lines)

    raise AssertionError(f"expected block for key '{key}'")


def markdown_table_under_heading(markdown_text: str, heading: str) -> tuple[list[str], list[dict[str, str]]]:
    heading_line = f"## {heading}"
    lines = markdown_text.splitlines()
    heading_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == heading_line:
            heading_index = index
            break
    if heading_index is None:
        raise AssertionError(f"missing heading: {heading_line}")

    section_lines: list[str] = []
    for line in lines[heading_index + 1 :]:
        if line.startswith("## "):
            break
        section_lines.append(line)

    table_lines = [line.strip() for line in section_lines if line.strip().startswith("|")]
    if len(table_lines) < 3:
        raise AssertionError(f"expected markdown table under heading: {heading_line}")

    headers = [column.strip() for column in table_lines[0].strip("|").split("|")]
    divider = [column.strip() for column in table_lines[1].strip("|").split("|")]
    if len(divider) != len(headers) or not all(set(column) <= {"-", ":"} and column for column in divider):
        raise AssertionError(f"invalid markdown table separator under heading: {heading_line}")

    rows: list[dict[str, str]] = []
    for raw_line in table_lines[2:]:
        values = [column.strip() for column in raw_line.strip("|").split("|")]
        if len(values) != len(headers):
            raise AssertionError(f"table row has {len(values)} columns, expected {len(headers)}: {raw_line}")
        rows.append(dict(zip(headers, values, strict=True)))

    return headers, rows


def extract_source_blocks(config_text: str) -> list[str]:
    data_sources_block = extract_named_block(config_text, "data_sources")
    lines = data_sources_block.splitlines()
    source_start_indexes = [index for index, line in enumerate(lines) if re.match(r"^\s*-\s+name:", line)]
    if not source_start_indexes:
        raise AssertionError("expected at least one data_sources entry")

    source_blocks: list[str] = []
    for position, start_index in enumerate(source_start_indexes):
        end_index = source_start_indexes[position + 1] if position + 1 < len(source_start_indexes) else len(lines)
        source_blocks.append("\n".join(lines[start_index:end_index]))
    return source_blocks


def source_block_by_name(config_text: str, source_name: str) -> str:
    for source_block in extract_source_blocks(config_text):
        name_match = re.search(r'^\s*-\s+name:\s*"([^"]+)"', source_block, re.MULTILINE)
        if name_match and name_match.group(1) == source_name:
            return source_block
    raise AssertionError(f"missing data source block for '{source_name}'")


def nested_keys(block: str, key: str) -> list[str]:
    lines = block.splitlines()
    nested_indent: int | None = None
    keys: list[str] = []

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if nested_indent is not None and indent <= nested_indent:
            break

        mapping_header = YAML_KEY_LINE.match(line)
        if mapping_header and mapping_header.group(1) == key:
            nested_indent = indent
            continue

        if nested_indent is not None and indent > nested_indent:
            key_match = re.match(r"^\s*([^:]+):", line)
            if key_match is None:
                continue
            source_key = key_match.group(1).strip()
            if source_key.startswith(("'", '"')) and source_key.endswith(("'", '"')):
                source_key = source_key[1:-1]
            keys.append(source_key)

    return keys


def scalar_value(block: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", block, re.MULTILINE)
    if match is None:
        raise AssertionError(f"expected scalar value for '{key}'")
    raw_value = match.group(1).strip()
    if raw_value.startswith(("'", '"')) and raw_value.endswith(("'", '"')):
        return raw_value[1:-1]
    return raw_value


def shared_data_source_scalar(config_text: str, key: str) -> str:
    values = {scalar_value(source_block, key) for source_block in extract_source_blocks(config_text)}
    if not values:
        raise AssertionError(f"expected at least one data source scalar for '{key}'")
    if len(values) != 1:
        raise AssertionError(f"expected a single shared '{key}' value across data sources, found {sorted(values)}")
    return next(iter(values))


def assert_ascii_crlf_without_bom(path: Path) -> None:
    payload = path.read_bytes()
    assert not payload.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
    payload.decode("ascii")
    assert b"\r\n" in payload
    payload_without_crlf = payload.replace(b"\r\n", b"")
    assert b"\n" not in payload_without_crlf
    assert b"\r" not in payload_without_crlf
