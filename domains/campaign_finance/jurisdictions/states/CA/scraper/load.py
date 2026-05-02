
from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    insert_organization,
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import Address, Organization, SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    link_entity_source_and_optional_mailing_address,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from ._load_config import (
    _CVR_TABLE,
    _FILERNAME_TABLE,
    _FILERS_TABLE,
    _TRANSACTION_TABLES,
    CACommitteeProfile,
    CAEntityRoles,
    CAFilerProfile,
    CAFilingLookupEntry,
    CALoadCounts,
    CATransactionTableConfig,
    TABLE_CONFIG_BY_NAME,
    load_cvr_fields,
    load_filername_fields,
    load_filers_fields,
    load_transaction_fields,
)
from .extract import (
    _normalize_state_code,
    _split_zip,
    build_ca_data_source,
    extract_committee_from_cvr,
    extract_employer,
    extract_name_raw,
    extract_occupation,
)
from .parse import parse_table

LOGGER = logging.getLogger(__name__)

_normalize_optional_text = normalize_optional_text

# Fallback transaction type when both TRAN_TYPE and FORM_TYPE are missing.
_TABLE_NAME_DEFAULTS = {"RCPT_CD": "RCPT", "EXPN_CD": "EXPN", "LOAN_CD": "LOAN"}


def ensure_ca_data_source(conn: psycopg.Connection) -> UUID:
    return ensure_data_source(conn, build_ca_data_source())


def _build_member_path(member_dir: Path, table_name: str) -> Path:
    return member_dir / f"{table_name}.TSV"


def _required_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"CA row is missing required {field_name}")
    return normalized_value


def _normalize_amendment_id(raw_value: str | None) -> str:
    return _normalize_optional_text(raw_value) or "0"


def _to_amendment_indicator(raw_value: str | None) -> str:
    return "N" if _normalize_amendment_id(raw_value) == "0" else "A"


def _parse_optional_ca_date(raw_value: str | None) -> date | None:
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    for date_format in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue
    return None


def _parse_required_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_text(raw_value, field_name).replace(",", "")
    try:
        return Decimal(normalized_value)
    except InvalidOperation as exc:
        raise ValueError(f"CA row has invalid {field_name}: {raw_value!r}") from exc


def _build_name(first: str | None, last: str | None, title: str | None = None, suffix: str | None = None) -> str | None:
    parts = [_normalize_optional_text(part) for part in (title, first, last, suffix)]
    normalized_parts = [part for part in parts if part is not None]
    if not normalized_parts:
        return None
    return " ".join(normalized_parts)


def _build_address(city: str | None, state: str | None, raw_zip: str | None) -> Address | None:
    normalized_city = _normalize_optional_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalize_optional_text(raw_zip)
    if normalized_city is None and normalized_state is None and normalized_zip is None:
        return None

    zip5, zip4 = _split_zip(raw_zip)
    normalized_city_upper = normalized_city.upper() if normalized_city is not None else None
    raw_parts = [part for part in (normalized_city_upper, normalized_state, normalized_zip) if part]
    return Address(
        raw_address=", ".join(raw_parts),
        city=normalized_city_upper,
        state=normalized_state,
        zip5=zip5,
        zip4=zip4,
    )


def _build_raw_fields(table_name: str, row: Mapping[str, str | None]) -> dict[str, object]:
    raw_fields = {"__table_name": table_name}
    raw_fields.update(dict(row))
    return raw_fields


def _select_ca_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _build_filing_lookup_key(filing_id: str | None, amendment_id: str | None) -> tuple[str, str]:
    return (_required_text(filing_id, "FILING_ID"), _normalize_amendment_id(amendment_id))


def _resolve_filing_lookup_entry(
    *,
    table_name: str,
    filing_lookup: Mapping[tuple[str, str], CAFilingLookupEntry],
    filing_lookup_key: tuple[str, str],
) -> CAFilingLookupEntry | None:
    filing_entry = filing_lookup.get(filing_lookup_key)
    if filing_entry is not None:
        return filing_entry

    filing_id, amendment_id = filing_lookup_key
    if amendment_id != "0":
        fallback_key = (filing_id, "0")
        filing_entry = filing_lookup.get(fallback_key)
        if filing_entry is not None:
            LOGGER.debug(
                "CA filing lookup used amendment-zero fallback for %s key=%r fallback=%r",
                table_name,
                filing_lookup_key,
                fallback_key,
            )
            return filing_entry

    return None


def _build_cvr_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
) -> SourceRecord:
    fields = load_cvr_fields()
    filing_id, amendment_id = _build_filing_lookup_key(row.get(fields["filing_id"]), row.get(fields["amendment_id"]))
    source_record_key = f"{_CVR_TABLE}:{filing_id}:{amendment_id}"
    raw_fields = _build_raw_fields(_CVR_TABLE, row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _build_transaction_source_record(
    table_name: str,
    data_source_id: UUID,
    row: Mapping[str, str | None],
) -> SourceRecord:
    fields = load_transaction_fields(table_name)
    filing_id, amendment_id = _build_filing_lookup_key(row.get(fields["filing_id"]), row.get(fields["amendment_id"]))
    transaction_id = _required_text(row.get(fields["transaction_id"]), fields["transaction_id"])
    source_record_key = f"{table_name}:{filing_id}:{amendment_id}:{transaction_id}"
    raw_fields = _build_raw_fields(table_name, row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _parse_filer_profiles(member_dir: Path) -> dict[str, CAFilerProfile]:
    profiles_by_filer_id: dict[str, CAFilerProfile] = {}

    # FILERS_CD pass: live export only contains FILER_ID, so we seed profiles
    # with the ID and leave filer_type/status to be filled by FILERNAME_CD.
    filers_fields = load_filers_fields()
    for row in parse_table(_build_member_path(member_dir, _FILERS_TABLE), _FILERS_TABLE):
        filer_id = _normalize_optional_text(row.get(filers_fields["filer_id"]))
        if filer_id is None:
            continue
        existing_profile = profiles_by_filer_id.get(filer_id)
        profiles_by_filer_id[filer_id] = CAFilerProfile(
            canonical_name=existing_profile.canonical_name if existing_profile is not None else None,
            filer_type=existing_profile.filer_type if existing_profile is not None else None,
            status=existing_profile.status if existing_profile is not None else None,
            address=existing_profile.address if existing_profile is not None else None,
        )

    filername_fields = load_filername_fields()
    for row in parse_table(_build_member_path(member_dir, _FILERNAME_TABLE), _FILERNAME_TABLE):
        filer_id = _normalize_optional_text(row.get(filername_fields["filer_id"]))
        if filer_id is None:
            continue
        existing_profile = profiles_by_filer_id.get(filer_id)
        profiles_by_filer_id[filer_id] = CAFilerProfile(
            canonical_name=_build_name(
                row.get(filername_fields["name_first"]),
                row.get(filername_fields["name_last"]),
                row.get(filername_fields["name_title"]),
                row.get(filername_fields["name_suffix"]),
            ),
            filer_type=_normalize_optional_text(row.get(filername_fields["filer_type"]))
            or (existing_profile.filer_type if existing_profile is not None else None),
            status=existing_profile.status if existing_profile is not None else None,
            address=_build_address(
                row.get(filername_fields["city"]),
                row.get(filername_fields["state"]),
                row.get(filername_fields["zip"]),
            ),
        )

    return profiles_by_filer_id


def _build_committee_profile(
    cvr_row: Mapping[str, str | None],
    *,
    filer_profiles: Mapping[str, CAFilerProfile],
) -> CACommitteeProfile:
    cvr_fields = load_cvr_fields()
    filer_id = _required_text(cvr_row.get(cvr_fields["filer_id"]), cvr_fields["filer_id"])
    filer_profile = filer_profiles.get(filer_id)
    committee_org = extract_committee_from_cvr(dict(cvr_row))

    canonical_name = (
        filer_profile.canonical_name
        if filer_profile is not None and filer_profile.canonical_name is not None
        else committee_org.canonical_name
    )
    identifiers = dict(committee_org.identifiers)
    identifiers["ca_filer_id"] = filer_id
    if filer_profile is not None and filer_profile.filer_type is not None:
        identifiers["ca_filer_type"] = filer_profile.filer_type
    if filer_profile is not None and filer_profile.status is not None:
        identifiers["ca_filer_status"] = filer_profile.status

    return CACommitteeProfile(
        organization=Organization(canonical_name=canonical_name, identifiers=identifiers),
        address=filer_profile.address if filer_profile is not None else None,
    )


def _resolve_committee_organization_id(
    conn: psycopg.Connection,
    committee_profile: CACommitteeProfile,
) -> UUID:
    filer_id = committee_profile.organization.identifiers["ca_filer_id"]
    existing_id = find_organization_by_identifier(conn, "ca_filer_id", filer_id)
    if existing_id is not None:
        return existing_id

    organization = committee_profile.organization
    if committee_profile.address is not None:
        organization = organization.model_copy(
            update={"primary_address_id": upsert_address(conn, committee_profile.address)}
        )
    return insert_organization(conn, organization)


def _build_ca_filing_fec_id(cvr_row: Mapping[str, str | None]) -> str:
    fields = load_cvr_fields()
    filer_id = _required_text(cvr_row.get(fields["filer_id"]), fields["filer_id"])
    filing_id = _required_text(cvr_row.get(fields["filing_id"]), fields["filing_id"])
    amendment_id = _normalize_amendment_id(cvr_row.get(fields["amendment_id"]))
    return f"CA-{filer_id}-{filing_id}-{amendment_id}"


def _load_filing_lookup_from_db(
    conn: psycopg.Connection,
) -> tuple[dict[tuple[str, str], CAFilingLookupEntry], dict[tuple[str, str], str]] | None:
    """Build filing lookup from existing CA filings in the database.

    Returns None if no CA filings exist, signalling that the CVR table
    must be processed from scratch. Otherwise returns (lookup, hash_by_key)
    where hash_by_key maps each (filing_id, amendment_id) to its active
    source_record.record_hash so callers can detect changed data.
    """
    rows = conn.execute(
        """
        SELECT f.id, f.filing_fec_id, f.committee_id, f.amendment_indicator,
               f.source_record_id, c.organization_id, sr.record_hash,
               f.report_type
        FROM cf.filing f
        JOIN cf.committee c ON f.committee_id = c.id
        JOIN core.source_record sr ON sr.id = f.source_record_id
        WHERE c.state = 'CA'
        """
    ).fetchall()
    if not rows:
        return None

    lookup: dict[tuple[str, str], CAFilingLookupEntry] = {}
    hash_by_key: dict[tuple[str, str], str] = {}
    for (
        filing_db_id,
        filing_fec_id,
        committee_id,
        amendment_indicator,
        source_record_id,
        org_id,
        record_hash,
        report_type,
    ) in rows:
        # filing_fec_id format: CA-{filer_id}-{filing_id}-{amendment_id}
        parts = filing_fec_id.split("-")
        if len(parts) != 4:
            continue
        key = (parts[2], parts[3])
        lookup[key] = CAFilingLookupEntry(
            filing_id=filing_db_id,
            committee_id=committee_id,
            committee_organization_id=org_id,
            amendment_indicator=amendment_indicator,
            source_record_id=source_record_id,
            form_type=report_type,
        )
        hash_by_key[key] = record_hash
    LOGGER.info("Loaded %d filing lookup entries from existing DB data", len(lookup))
    return lookup, hash_by_key


def _cvr_row_unchanged(
    row: Mapping[str, str | None],
    cvr_fields: dict[str, str],
    db_hash_by_key: dict[tuple[str, str], str],
) -> bool:
    """Return True if this CVR row already exists in the DB with the same hash."""
    preview_key = _build_filing_lookup_key(row.get(cvr_fields["filing_id"]), row.get(cvr_fields["amendment_id"]))
    if preview_key not in db_hash_by_key:
        return False
    current_hash = compute_record_hash(_build_raw_fields(_CVR_TABLE, row))
    return db_hash_by_key[preview_key] == current_hash


def _upsert_cvr_filing_entry(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    cvr_fields: dict[str, str],
    data_source_id: UUID,
    filer_profiles: Mapping[str, CAFilerProfile],
) -> CAFilingLookupEntry:
    """Upsert a single CVR row into filings and return its lookup entry."""
    source_record = _build_cvr_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        source_record_id = _select_ca_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record.source_record_key,
        )
        if source_record_id is None:
            raise RuntimeError(
                "CA filing source_record insert reported a conflict, but the existing source_record row "
                f"could not be selected for {source_record.source_record_key!r}"
            )

    committee_profile = _build_committee_profile(row, filer_profiles=filer_profiles)
    organization_id = _resolve_committee_organization_id(conn, committee_profile)
    committee_address_id = (
        upsert_address(conn, committee_profile.address) if committee_profile.address is not None else None
    )
    committee_id = ensure_state_committee(
        conn,
        state="CA",
        native_committee_id=_required_text(row.get(cvr_fields["filer_id"]), cvr_fields["filer_id"]),
        organization_id=organization_id,
    )
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=organization_id,
        source_record_id=source_record_id,
        extraction_role="committee",
        address_id=committee_address_id,
    )

    filing = Filing(
        filing_fec_id=_build_ca_filing_fec_id(row),
        committee_id=committee_id,
        report_type=_normalize_optional_text(row.get(cvr_fields["form_type"]))
        or _normalize_optional_text(row.get(cvr_fields["statement_type"])),
        amendment_indicator=_to_amendment_indicator(row.get(cvr_fields["amendment_id"])),
        filing_name=committee_profile.organization.canonical_name,
        receipt_date=_parse_optional_ca_date(row.get(cvr_fields["report_date"])),
        accepted_date=_parse_optional_ca_date(row.get(cvr_fields["report_date"])),
        source_record_id=source_record_id,
    )
    filing_id = upsert_filing(conn, filing)
    return CAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        committee_organization_id=organization_id,
        amendment_indicator=filing.amendment_indicator,
        source_record_id=source_record_id,
        form_type=_normalize_optional_text(row.get(cvr_fields["form_type"])),
    )


def _upsert_ca_filing_lookup(
    conn: psycopg.Connection,
    *,
    member_dir: Path,
    data_source_id: UUID,
) -> dict[tuple[str, str], CAFilingLookupEntry]:
    # Seed lookup from existing DB filings to avoid reprocessing CVR rows
    # that were already loaded in a previous run (~679K rows, ~80 min).
    db_result = _load_filing_lookup_from_db(conn)
    if db_result is not None:
        lookup, db_hash_by_key = db_result
    else:
        lookup, db_hash_by_key = {}, {}

    filer_profiles = _parse_filer_profiles(member_dir)
    cvr_fields = load_cvr_fields()
    # _load_filing_lookup_from_db() performs a SELECT which starts a transaction.
    # Commit it so periodic commits in the CVR loop actually fire.
    conn.commit()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    skipped_cvr_rows = 0
    processed_cvr_rows = 0
    for row in parse_table(_build_member_path(member_dir, _CVR_TABLE), _CVR_TABLE):
        try:
            if _cvr_row_unchanged(row, cvr_fields, db_hash_by_key):
                processed_cvr_rows += 1
                continue
            if manages_outer_transaction:
                ensure_transaction_open(conn)
            with conn.transaction():
                lookup_key = _build_filing_lookup_key(
                    row.get(cvr_fields["filing_id"]), row.get(cvr_fields["amendment_id"])
                )
                lookup[lookup_key] = _upsert_cvr_filing_entry(
                    conn,
                    row,
                    cvr_fields=cvr_fields,
                    data_source_id=data_source_id,
                    filer_profiles=filer_profiles,
                )
        except Exception:  # noqa: BLE001
            skipped_cvr_rows += 1
            if skipped_cvr_rows <= 5:
                LOGGER.exception("Skipping malformed CA CVR row")

        processed_cvr_rows += 1
        if processed_cvr_rows % 500 == 0:
            commit_managed_transaction(conn, manages_outer_transaction)

    commit_managed_transaction(conn, manages_outer_transaction)
    if skipped_cvr_rows > 0:
        LOGGER.warning("Skipped %d malformed CVR rows during filing lookup build", skipped_cvr_rows)

    return lookup


def _load_counterparty_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: Mapping[str, object],
    committee_organization_id: UUID,
    committee_source_record_id: UUID,
    roles: CAEntityRoles,
) -> UUID | None:
    address = extracted.get("address")
    address_id = upsert_address(conn, address) if isinstance(address, Address) else None
    if address_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=roles.address,
            address_id=None,
        )

    # Extract output keys use the counterparty prefix (donor/payee/lender),
    # which is always roles.person for all three transaction types.
    person = extracted.get(f"{roles.person}_person")
    organization = extracted.get(f"{roles.person}_org")

    person_id = resolve_person_by_name_and_zip(conn, person if hasattr(person, "canonical_name") else None, address)  # type: ignore[arg-type]
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=roles.person,
            address_id=address_id,
        )

    organization_id = resolve_organization_by_canonical_name(
        conn,
        organization if hasattr(organization, "canonical_name") else None,  # type: ignore[arg-type]
    )
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=roles.organization,
            address_id=address_id,
        )

    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_organization_id,
        source_record_id=committee_source_record_id,
        extraction_role=roles.committee,
        address_id=None,
    )
    return address_id


def _ca_is_f496_independent_expenditure(table_name: str, filing_entry: CAFilingLookupEntry) -> bool:
    """True when an EXPN_CD row belongs to an F496 (24-hour IE report) filing."""
    return table_name == "EXPN_CD" and filing_entry.form_type is not None and filing_entry.form_type.upper() == "F496"


def _upsert_transaction_row(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    table_config: CATransactionTableConfig,
    data_source_id: UUID,
    filing_lookup: Mapping[tuple[str, str], CAFilingLookupEntry],
) -> bool:
    table_fields = load_transaction_fields(table_config.table_name)

    filing_lookup_key = _build_filing_lookup_key(
        row.get(table_fields["filing_id"]),
        row.get(table_fields["amendment_id"]),
    )
    filing_entry = _resolve_filing_lookup_entry(
        table_name=table_config.table_name,
        filing_lookup=filing_lookup,
        filing_lookup_key=filing_lookup_key,
    )
    if filing_entry is None:
        return False

    transaction_source_record = _build_transaction_source_record(table_config.table_name, data_source_id, row)
    source_record_id = try_insert_source_record(conn, transaction_source_record)
    if source_record_id is None:
        return False

    extracted = table_config.extract_row(dict(row))
    contributor_address_id = _load_counterparty_entities(
        conn,
        source_record_id=source_record_id,
        extracted=extracted,
        committee_organization_id=filing_entry.committee_organization_id,
        committee_source_record_id=source_record_id,
        roles=table_config.entity_roles,
    )

    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=table_config.entity_roles.person_lookup_roles,
        organization_roles=table_config.entity_roles.organization_lookup_roles,
    )
    address = extracted.get("address")
    contributor_state = address.state if isinstance(address, Address) else None
    contributor_zip = address.zip5 if isinstance(address, Address) else None
    contributor_city = address.city if isinstance(address, Address) else None

    transaction_type = _normalize_optional_text(row.get(table_fields["transaction_type"]))
    # Live CA data rarely populates TRAN_TYPE for RCPT_CD/EXPN_CD; fall back
    # to FORM_TYPE (schedule letter), then to a table-derived default.
    if transaction_type is None:
        transaction_type = _normalize_optional_text(row.get(table_fields["form_type"]))
    if transaction_type is None:
        transaction_type = _TABLE_NAME_DEFAULTS.get(table_config.table_name)
    if transaction_type is None:
        raise ValueError(f"CA {table_config.table_name} row is missing {table_fields['transaction_type']}")

    transaction_type = transaction_type.upper()
    # F496 is a 24-hour late independent expenditure report. EXPN_CD rows
    # under F496 filings are independent expenditures regardless of their
    # row-level EXPN_CODE / FORM_TYPE values.
    # TODO: Form 461 Schedule E is a separate IE reporting form — not handled here.
    # TODO: support_oppose direction requires parsing F496 candidate/ballot target fields.
    if _ca_is_f496_independent_expenditure(table_config.table_name, filing_entry):
        transaction_type = "Independent Expenditure"

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_entry.filing_id,
            committee_id=filing_entry.committee_id,
            transaction_type=transaction_type,
            transaction_identifier=transaction_source_record.source_record_key,
            transaction_date=_parse_optional_ca_date(row.get(table_fields["transaction_date"])),
            amount=_parse_required_amount(row.get(table_fields["amount"]), table_fields["amount"]),
            contributor_name_raw=extract_name_raw(extracted),
            contributor_employer=extract_employer(extracted),
            contributor_occupation=extract_occupation(extracted),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=filing_entry.committee_id,
            amendment_indicator=filing_entry.amendment_indicator,
            source_record_id=source_record_id,
        ),
    )
    return True


def _try_load_transaction_row(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    table_config: CATransactionTableConfig,
    data_source_id: UUID,
    filing_lookup: Mapping[tuple[str, str], CAFilingLookupEntry],
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _upsert_transaction_row(
                conn,
                row=row,
                table_config=table_config,
                data_source_id=data_source_id,
                filing_lookup=filing_lookup,
            )
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Failed loading CA %s row transaction_id=%s",
            table_config.table_name,
            row.get(load_transaction_fields(table_config.table_name)["transaction_id"]),
        )
        return None


def load_ca_member_directory_with_filings(
    conn: psycopg.Connection,
    member_dir: str | Path,
    *,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    started_at = time.monotonic()
    validated_row_limit = validated_limit(limit)
    resolved_member_dir = Path(member_dir)
    data_source_id = ensure_ca_data_source(conn)
    # Commit data_source insert so _upsert_ca_filing_lookup sees IDLE state
    # and its periodic commits actually fire (manages_outer_transaction=True).
    conn.commit()
    filing_lookup = _upsert_ca_filing_lookup(conn, member_dir=resolved_member_dir, data_source_id=data_source_id)

    counts = CALoadCounts()
    processed_rows = 0
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for table_name in _TRANSACTION_TABLES:
        # Pass year_from to the parser — it filters rows by transaction date
        # before they reach the DB. Only effective for transaction tables.
        parser = parse_table(_build_member_path(resolved_member_dir, table_name), table_name, year_from=year_from)
        table_config = TABLE_CONFIG_BY_NAME[table_name]
        for row in parser:
            processed_rows += 1
            if validated_row_limit is not None and processed_rows > validated_row_limit:
                break

            inserted = _try_load_transaction_row(
                conn,
                row=row,
                table_config=table_config,
                data_source_id=data_source_id,
                filing_lookup=filing_lookup,
                manages_outer_transaction=manages_outer_transaction,
            )
            if inserted is None:
                counts.errors += 1
            elif inserted:
                counts.inserted += 1
            else:
                counts.skipped += 1

            if (counts.inserted + counts.skipped + counts.errors) % 1_000 == 0:
                commit_managed_transaction(conn, manages_outer_transaction)

        counts.quarantined += parser.skipped
        if validated_row_limit is not None and processed_rows >= validated_row_limit:
            break

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=counts.quarantined,
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )
