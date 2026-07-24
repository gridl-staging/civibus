
from __future__ import annotations

from collections import Counter
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Iterator, Union

from domains.campaign_finance.types import (
    Contribution527,
    Expenditure527,
    Filing8872,
    PoliticalOrganization527,
)

LOGGER = logging.getLogger(__name__)
_CONVERSION_ERROR_LOG_LIMIT = 3

# Column tuples per record type (excludes the Record Type dispatch field).
# Field names are snake_case conversions of the IRS PolOrgsFileLayout.doc headers.
IRS_527_COLUMNS_BY_RECORD_TYPE: dict[str, tuple[str, ...]] = {
    "1": (
        "form_type",
        "form_id_number",
        "initial_report_indicator",
        "amended_report_indicator",
        "final_report_indicator",
        "ein",
        "organization_name",
        "mailing_address_1",
        "mailing_address_2",
        "mailing_address_city",
        "mailing_address_state",
        "mailing_address_zip_code",
        "mailing_address_zip_ext",
        "e_mail_address",
        "established_date",
        "custodian_name",
        "custodian_address_1",
        "custodian_address_2",
        "custodian_address_city",
        "custodian_address_state",
        "custodian_address_zip_code",
        "custodian_address_zip_ext",
        "contact_person_name",
        "contact_address_1",
        "contact_address_2",
        "contact_address_city",
        "contact_address_state",
        "contact_address_zip_code",
        "contact_address_zip_ext",
        "business_address_1",
        "business_address_2",
        "business_address_city",
        "business_address_state",
        "business_address_zip_code",
        "business_address_zip_ext",
        "exempt_8872_indicator",
        "exempt_state",
        "exempt_990_indicator",
        "purpose",
        "material_change_date",
        "insert_datetime",
        "related_entity_bypass",
        "eain_bypass",
    ),
    "2": (
        "form_type",
        "form_id_number",
        "period_begin_date",
        "period_end_date",
        "initial_report_indicator",
        "amended_report_indicator",
        "final_report_indicator",
        "change_of_address_indicator",
        "organization_name",
        "ein",
        "mailing_address_1",
        "mailing_address_2",
        "mailing_address_city",
        "mailing_address_state",
        "mailing_address_zip_code",
        "mailing_address_zip_ext",
        "e_mail_address",
        "org_formation_date",
        "custodian_name",
        "custodian_address_1",
        "custodian_address_2",
        "custodian_address_city",
        "custodian_address_state",
        "custodian_address_zip_code",
        "custodian_address_zip_ext",
        "contact_person_name",
        "contact_address_1",
        "contact_address_2",
        "contact_address_city",
        "contact_address_state",
        "contact_address_zip_code",
        "contact_address_zip_ext",
        "business_address_1",
        "business_address_2",
        "business_address_city",
        "business_address_state",
        "business_address_zip_code",
        "business_address_zip_ext",
        "qtr_indicator",
        "monthly_rpt_month",
        "pre_elect_type",
        "pre_or_post_elect_date",
        "pre_or_post_elect_state",
        "sched_a_ind",
        "total_sched_a",
        "sched_b_ind",
        "total_sched_b",
        "insert_datetime",
    ),
    "A": (
        "form_id_number",
        "sched_a_id",
        "org_name",
        "ein",
        "contributor_name",
        "contributor_address_1",
        "contributor_address_2",
        "contributor_address_city",
        "contributor_address_state",
        "contributor_address_zip_code",
        "contributor_address_zip_ext",
        "contributor_employer",
        "contribution_amount",
        "contributor_occupation",
        "agg_contribution_ytd",
        "contribution_date",
    ),
    "B": (
        "form_id_number",
        "sched_b_id",
        "org_name",
        "ein",
        "reciepient_name",
        "reciepient_address_1",
        "reciepient_address_2",
        "reciepient_address_city",
        "reciepient_address_st",
        "reciepient_address_zip_code",
        "reciepient_address_zip_ext",
        "reciepient_employer",
        "expenditure_amount",
        "recipient_occupation",
        "expenditure_date",
        "expenditure_purpose",
    ),
}


Irs527Record = Union[PoliticalOrganization527, Filing8872, Contribution527, Expenditure527]


# -- type coercion helpers --


def _parse_indicator(value: str | None) -> bool | None:
    """Parse IRS indicator field: "1" → True, "0" → False, else None."""
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def _parse_date(value: str | None) -> date | None:
    """Parse IRS YYYYMMDD date string to date object.

    Format verified against the live FullDataFile 2026-07-06: every dated
    field (type A/B/2 dates, established date, header date) is YYYYMMDD.
    Anything else (empty, datetime strings, out-of-range) returns None.
    """
    if not value or len(value) != 8:
        return None
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except (ValueError, IndexError):
        return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _recency_cutoff_date() -> date:
    """5-year window: current year minus 4.  For 2026 → 2022-01-01."""
    return date(date.today().year - 4, 1, 1)


# -- streaming row dispatch --


def iter_irs_527_rows(stream: IO[str]) -> Iterator[tuple[str, dict[str, str | None]]]:
    """Yield (record_type, row_dict) for each modeled IRS 527 record.

    Dispatches each line to its record-type column schema. Non-modeled
    types (H, D, R, E, F) are silently skipped. Empty fields normalize to None.
    """
    for line in stream:
        stripped = line.strip()
        if not stripped:
            continue

        parts = stripped.split("|")
        # Handle pipe-terminated rows: remove trailing empty element
        if parts and parts[-1] == "":
            parts = parts[:-1]

        record_type = parts[0] if parts else ""
        if record_type not in IRS_527_COLUMNS_BY_RECORD_TYPE:
            continue

        columns = IRS_527_COLUMNS_BY_RECORD_TYPE[record_type]
        data_fields = parts[1:]

        # Reject dramatically malformed rows (less than half expected fields)
        if len(data_fields) < len(columns) // 2:
            LOGGER.warning(
                "Skipping malformed type %s row: expected ~%d fields, got %d",
                record_type,
                len(columns),
                len(data_fields),
            )
            continue

        # Build dict, normalizing empty → None and stripping whitespace
        row: dict[str, str | None] = {}
        for i, col in enumerate(columns):
            val = data_fields[i] if i < len(data_fields) else ""
            cleaned = val.strip() if val else ""
            row[col] = cleaned if cleaned else None

        yield record_type, row


# -- record-type → Pydantic model mappers --


def _type_1_to_model(row: dict[str, str | None]) -> PoliticalOrganization527:
    return PoliticalOrganization527(
        form_type=row["form_type"],
        form_id_number=row["form_id_number"],
        ein=row["ein"],
        name=row["organization_name"],
        mailing_address_1=row.get("mailing_address_1"),
        mailing_address_2=row.get("mailing_address_2"),
        mailing_address_city=row.get("mailing_address_city"),
        mailing_address_state=row.get("mailing_address_state"),
        mailing_address_zip=row.get("mailing_address_zip_code"),
        mailing_address_zip_ext=row.get("mailing_address_zip_ext"),
        email_address=row.get("e_mail_address"),
        established_date=_parse_date(row.get("established_date")),
        custodian_name=row.get("custodian_name"),
        custodian_address_1=row.get("custodian_address_1"),
        custodian_address_2=row.get("custodian_address_2"),
        custodian_address_city=row.get("custodian_address_city"),
        custodian_address_state=row.get("custodian_address_state"),
        custodian_address_zip=row.get("custodian_address_zip_code"),
        custodian_address_zip_ext=row.get("custodian_address_zip_ext"),
        contact_person_name=row.get("contact_person_name"),
        contact_address_1=row.get("contact_address_1"),
        contact_address_2=row.get("contact_address_2"),
        contact_address_city=row.get("contact_address_city"),
        contact_address_state=row.get("contact_address_state"),
        contact_address_zip=row.get("contact_address_zip_code"),
        contact_address_zip_ext=row.get("contact_address_zip_ext"),
        business_address_1=row.get("business_address_1"),
        business_address_2=row.get("business_address_2"),
        business_address_city=row.get("business_address_city"),
        business_address_state=row.get("business_address_state"),
        business_address_zip=row.get("business_address_zip_code"),
        business_address_zip_ext=row.get("business_address_zip_ext"),
        purpose=row.get("purpose"),
        material_change_date=_parse_date(row.get("material_change_date")),
        insert_datetime=row.get("insert_datetime"),
        initial_report_indicator=_parse_indicator(row.get("initial_report_indicator")),
        amended_report_indicator=_parse_indicator(row.get("amended_report_indicator")),
        final_report_indicator=_parse_indicator(row.get("final_report_indicator")),
        exempt_8872_indicator=_parse_indicator(row.get("exempt_8872_indicator")),
        exempt_state=row.get("exempt_state"),
        exempt_990_indicator=_parse_indicator(row.get("exempt_990_indicator")),
        related_entity_bypass=row.get("related_entity_bypass"),
        eain_bypass=row.get("eain_bypass"),
    )


def _type_2_to_model(row: dict[str, str | None]) -> Filing8872:
    return Filing8872(
        form_type=row["form_type"],
        form_id_number=row["form_id_number"],
        ein=row["ein"],
        period_begin_date=_parse_date(row["period_begin_date"]),
        period_end_date=_parse_date(row["period_end_date"]),
        organization_name=row.get("organization_name"),
        mailing_address_1=row.get("mailing_address_1"),
        mailing_address_2=row.get("mailing_address_2"),
        mailing_address_city=row.get("mailing_address_city"),
        mailing_address_state=row.get("mailing_address_state"),
        mailing_address_zip=row.get("mailing_address_zip_code"),
        mailing_address_zip_ext=row.get("mailing_address_zip_ext"),
        email_address=row.get("e_mail_address"),
        change_of_address_indicator=_parse_indicator(row.get("change_of_address_indicator")),
        org_formation_date=_parse_date(row.get("org_formation_date")),
        custodian_name=row.get("custodian_name"),
        custodian_address_1=row.get("custodian_address_1"),
        custodian_address_2=row.get("custodian_address_2"),
        custodian_address_city=row.get("custodian_address_city"),
        custodian_address_state=row.get("custodian_address_state"),
        custodian_address_zip=row.get("custodian_address_zip_code"),
        custodian_address_zip_ext=row.get("custodian_address_zip_ext"),
        contact_person_name=row.get("contact_person_name"),
        contact_address_1=row.get("contact_address_1"),
        contact_address_2=row.get("contact_address_2"),
        contact_address_city=row.get("contact_address_city"),
        contact_address_state=row.get("contact_address_state"),
        contact_address_zip=row.get("contact_address_zip_code"),
        contact_address_zip_ext=row.get("contact_address_zip_ext"),
        business_address_1=row.get("business_address_1"),
        business_address_2=row.get("business_address_2"),
        business_address_city=row.get("business_address_city"),
        business_address_state=row.get("business_address_state"),
        business_address_zip=row.get("business_address_zip_code"),
        business_address_zip_ext=row.get("business_address_zip_ext"),
        initial_report_indicator=_parse_indicator(row.get("initial_report_indicator")),
        amended_report_indicator=_parse_indicator(row.get("amended_report_indicator")),
        final_report_indicator=_parse_indicator(row.get("final_report_indicator")),
        quarterly_indicator=_parse_indicator(row.get("qtr_indicator")),
        monthly_report_month=row.get("monthly_rpt_month"),
        pre_election_type=row.get("pre_elect_type"),
        pre_or_post_election_date=_parse_date(row.get("pre_or_post_elect_date")),
        pre_or_post_election_state=row.get("pre_or_post_elect_state"),
        sched_a_indicator=_parse_indicator(row.get("sched_a_ind")),
        total_sched_a=_parse_decimal(row.get("total_sched_a")),
        sched_b_indicator=_parse_indicator(row.get("sched_b_ind")),
        total_sched_b=_parse_decimal(row.get("total_sched_b")),
        insert_datetime=row.get("insert_datetime"),
    )


def _type_a_to_model(row: dict[str, str | None]) -> Contribution527:
    return Contribution527(
        form_id_number=row["form_id_number"],
        sched_a_id=row["sched_a_id"],
        ein=row["ein"],
        contributor_name=row["contributor_name"],
        amount=_parse_decimal(row["contribution_amount"]),
        contribution_date=_parse_date(row["contribution_date"]),
        aggregate_ytd=_parse_decimal(row["agg_contribution_ytd"]),
        org_name=row.get("org_name"),
        contributor_address_1=row.get("contributor_address_1"),
        contributor_address_2=row.get("contributor_address_2"),
        contributor_address_city=row.get("contributor_address_city"),
        contributor_address_state=row.get("contributor_address_state"),
        contributor_address_zip=row.get("contributor_address_zip_code"),
        contributor_address_zip_ext=row.get("contributor_address_zip_ext"),
        contributor_employer=row.get("contributor_employer"),
        contributor_occupation=row.get("contributor_occupation"),
    )


def _type_b_to_model(row: dict[str, str | None]) -> Expenditure527:
    # IRS uses "RECIEPIENT" (typo) in column names; model normalizes to "recipient"
    return Expenditure527(
        form_id_number=row["form_id_number"],
        sched_b_id=row["sched_b_id"],
        ein=row["ein"],
        recipient_name=row["reciepient_name"],
        amount=_parse_decimal(row["expenditure_amount"]),
        expenditure_date=_parse_date(row["expenditure_date"]),
        purpose=row["expenditure_purpose"],
        org_name=row.get("org_name"),
        recipient_address_1=row.get("reciepient_address_1"),
        recipient_address_2=row.get("reciepient_address_2"),
        recipient_address_city=row.get("reciepient_address_city"),
        recipient_address_state=row.get("reciepient_address_st"),
        recipient_address_zip=row.get("reciepient_address_zip_code"),
        recipient_address_zip_ext=row.get("reciepient_address_zip_ext"),
        recipient_employer=row.get("reciepient_employer"),
        recipient_occupation=row.get("recipient_occupation"),
    )


def _log_conversion_error(
    record_type: str,
    row: dict[str, str | None],
    error: Exception,
    *,
    skipped_count: int,
) -> None:
    if skipped_count > _CONVERSION_ERROR_LOG_LIMIT:
        return
    LOGGER.warning(
        "Skipping type %s row due to conversion error: %s (%s: %s)",
        record_type,
        row.get("form_id_number", "???"),
        type(error).__name__,
        _first_error_line(error),
    )


def _first_error_line(error: Exception) -> str:
    message = str(error).splitlines()
    return message[0] if message else ""


def _log_conversion_error_summary(skipped_counts: Counter[str]) -> None:
    for record_type, skipped_count in sorted(skipped_counts.items()):
        if skipped_count <= _CONVERSION_ERROR_LOG_LIMIT:
            continue
        LOGGER.warning(
            "Skipped %d type %s rows due to conversion errors; suppressed %d after the first %d",
            skipped_count,
            record_type,
            skipped_count - _CONVERSION_ERROR_LOG_LIMIT,
            _CONVERSION_ERROR_LOG_LIMIT,
        )


def _is_recent_or_undated(raw_date: str | None, *, cutoff: date) -> bool:
    parsed_date = _parse_date(raw_date)
    return parsed_date is None or parsed_date >= cutoff


# -- public streaming entry point --


def read_irs_527_records(txt_path: Path) -> Iterator[Irs527Record]:
    """Stream typed Pydantic models from an IRS 527 FullDataFile.txt.

    Applies a 5-year recency filter to dated record types (2, A, B).
    Type 1 organization records are always emitted for join support.
    """
    cutoff = _recency_cutoff_date()
    skipped_conversion_counts: Counter[str] = Counter()

    with txt_path.open(encoding="latin-1") as f:
        for record_type, row in iter_irs_527_rows(f):
            try:
                if record_type == "1":
                    yield _type_1_to_model(row)
                elif record_type == "2":
                    if not _is_recent_or_undated(row.get("period_begin_date"), cutoff=cutoff):
                        continue
                    model = _type_2_to_model(row)
                    yield model
                elif record_type == "A":
                    if not _is_recent_or_undated(row.get("contribution_date"), cutoff=cutoff):
                        continue
                    model = _type_a_to_model(row)
                    yield model
                elif record_type == "B":
                    if not _is_recent_or_undated(row.get("expenditure_date"), cutoff=cutoff):
                        continue
                    model = _type_b_to_model(row)
                    yield model
            except Exception as error:
                skipped_conversion_counts[record_type] += 1
                _log_conversion_error(
                    record_type,
                    row,
                    error,
                    skipped_count=skipped_conversion_counts[record_type],
                )
    _log_conversion_error_summary(skipped_conversion_counts)
