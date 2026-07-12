"""Parser for PHL Carto SQL JSON rows into typed Pydantic records.

The Carto endpoint returns 80+ raw fields per row; this module retains
only the canonical-mapping subset listed in `config.yaml::field_mappings`
plus a small number of pass-through fields that the loader needs (e.g.
office level for routing). Anything else is preserved on the source-record
`raw_fields` JSON for future-loader use.

See `docs/reference/research/phl_campaign_finance_contract_2026_04_25.md` for the
full live column inventory.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Iterator

from pydantic import BaseModel, ConfigDict, field_validator


class PHLCampaignFinanceRow(BaseModel):
    """One PHL campaign finance transaction (contribution or expenditure).

    Both `campfin_contributions` and `campfin_expenditures` share most
    columns. Donor-side and payee-side fields are unified here under
    `counterparty_*` so the loader does not need separate row types per
    table; `is_expenditure` distinguishes direction.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    # Identity
    transaction_id: str
    transaction_date: date
    transaction_amount: Decimal
    transaction_type: str | None = None
    transaction_description: str | None = None
    transaction_supertype: str | None = None
    is_expenditure: bool

    # Filer / committee
    filer_id: str | None = None
    filer_name: str
    filer_type: str | None = None
    filer_city: str | None = None
    filer_state: str | None = None
    filer_zip: str | None = None
    filer_candidate_name: str | None = None

    # Counterparty (donor for contributions, payee for expenditures)
    counterparty_name: str
    counterparty_name_std: str | None = None
    counterparty_type: str | None = None
    counterparty_city: str | None = None
    counterparty_state: str | None = None
    counterparty_zip: str | None = None
    counterparty_zip4: str | None = None
    counterparty_occupation: str | None = None
    counterparty_employer: str | None = None

    # Filing context
    report_year: int | None = None
    report_id: str | None = None
    report_filed_by: str | None = None
    report_url: str | None = None
    candidate_office: str | None = None
    office_level: str | None = None

    @field_validator("transaction_date", mode="before")
    @classmethod
    def _coerce_date(cls, value: Any) -> date | str:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            # Carto returns ISO-8601 with 'Z' suffix or naive form
            normalized = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized).date()
            except ValueError:
                # Fall back to date-only ISO
                return date.fromisoformat(value[:10])
        raise TypeError(f"Cannot coerce {value!r} to date")

    @field_validator("transaction_amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None or value == "":
            raise ValueError("transaction_amount is required and must be numeric")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"transaction_amount {value!r} is not a valid decimal") from exc


def parse_phl_carto_row(
    raw: dict[str, Any],
    *,
    is_expenditure: bool,
) -> PHLCampaignFinanceRow:
    """Map one Carto row dict to a typed PHLCampaignFinanceRow.

    `is_expenditure=True` selects payee_* columns from the raw row; otherwise
    selects donor_* columns. The Carto schema unfortunately uses different
    counterparty prefixes per table, so the caller must declare the side.
    """
    counterparty_prefix = "payee" if is_expenditure else "donor"
    return PHLCampaignFinanceRow(
        transaction_id=str(raw["transaction_id"]),
        transaction_date=raw["transaction_date"],
        transaction_amount=raw["transaction_amount"],
        transaction_type=_normalize_optional_text(raw.get("transaction_type")),
        transaction_description=_normalize_optional_text(raw.get("transaction_description")),
        transaction_supertype=_normalize_optional_text(raw.get("transaction_supertype")),
        is_expenditure=is_expenditure,
        filer_id=_normalize_optional_text(raw.get("filer_id")),
        filer_name=str(raw.get("filer_name") or ""),
        filer_type=_normalize_optional_text(raw.get("filer_type")),
        filer_city=_normalize_optional_text(raw.get("filer_city")),
        filer_state=_normalize_optional_text(raw.get("filer_state")),
        filer_zip=_normalize_optional_text(raw.get("filer_zip")),
        filer_candidate_name=_normalize_optional_text(raw.get("filer_candidate_name")),
        counterparty_name=str(raw.get(f"{counterparty_prefix}_name") or ""),
        counterparty_name_std=_normalize_optional_text(raw.get(f"{counterparty_prefix}_name_std")),
        counterparty_type=_normalize_optional_text(raw.get(f"{counterparty_prefix}_type")),
        counterparty_city=_normalize_optional_text(raw.get(f"{counterparty_prefix}_city")),
        counterparty_state=_normalize_optional_text(raw.get(f"{counterparty_prefix}_state")),
        counterparty_zip=_normalize_optional_text(raw.get(f"{counterparty_prefix}_zip")),
        counterparty_zip4=_normalize_optional_text(raw.get(f"{counterparty_prefix}_zip4")),
        counterparty_occupation=_normalize_optional_text(raw.get(f"{counterparty_prefix}_occupation")),
        counterparty_employer=_normalize_optional_text(raw.get(f"{counterparty_prefix}_employer_name")),
        report_year=_optional_int(raw.get("report_year")),
        report_id=_normalize_optional_text(raw.get("report_id")),
        report_filed_by=_normalize_optional_text(raw.get("report_filed_by")),
        report_url=_normalize_optional_text(raw.get("report_url")),
        candidate_office=_normalize_optional_text(raw.get("candidate_office")),
        office_level=_normalize_optional_text(raw.get("office_level")),
    )


def parse_phl_carto_rows(
    raw_rows: Iterable[dict[str, Any]],
    *,
    is_expenditure: bool,
) -> Iterator[PHLCampaignFinanceRow]:
    """Map an iterable of raw Carto rows; skips rows missing required fields."""
    for raw in raw_rows:
        if raw.get("transaction_id") is None or raw.get("transaction_amount") is None:
            # Required field missing — drop rather than raise; Carto sometimes
            # returns rows with NULL amounts (pending corrections etc.).
            continue
        yield parse_phl_carto_row(raw, is_expenditure=is_expenditure)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
