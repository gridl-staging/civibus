
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from core.db import get_connection, select_data_source
from core.types.python.models import DataSource
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source, select_data_source_id
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata
from domains.civics.loaders.official_rosters.source_templates import roster_source_templates

_DEFAULT_TEMPLATE_CADENCE = "weekly"


@dataclass(frozen=True, slots=True)
class RosterSourceTemplate:

    registry_source_id: str
    name: str
    source_url: str
    body_key: str
    cadence: str
    jurisdiction: str

    @property
    def notes_payload(self) -> dict[str, object]:
        return {
            "roster_source": True,
            "registry_source_id": self.registry_source_id,
            "body_key": self.body_key,
        }

    @property
    def notes_json(self) -> str:
        return json.dumps(self.notes_payload, sort_keys=True)

    def as_data_source(self) -> DataSource:
        return DataSource(
            domain="civics",
            jurisdiction=self.jurisdiction,
            name=self.name,
            source_url=self.source_url,
            source_format="html",
            update_frequency=self.cadence,
            notes=self.notes_json,
        )


def list_roster_source_templates() -> tuple[RosterSourceTemplate, ...]:
    templates_by_source_id: dict[str, RosterSourceTemplate] = {}

    for template in roster_source_templates():
        templates_by_source_id[template.registry_source_id] = RosterSourceTemplate(
            registry_source_id=template.registry_source_id,
            name=template.name,
            source_url=template.source_url,
            body_key=template.body_key,
            cadence=_DEFAULT_TEMPLATE_CADENCE,
            jurisdiction=template.data_source_jurisdiction,
        )

    for metadata in list_nc_roster_source_metadata():
        templates_by_source_id[metadata.source_id] = RosterSourceTemplate(
            registry_source_id=metadata.source_id,
            name=metadata.name,
            source_url=metadata.source_url,
            body_key=metadata.body_key,
            cadence=metadata.cadence,
            jurisdiction=metadata.jurisdiction,
        )

    return tuple(sorted(templates_by_source_id.values(), key=lambda template: (template.jurisdiction, template.name)))


def _decode_notes(notes: str | None) -> dict[str, object] | None:
    if notes is None:
        return None
    try:
        parsed = json.loads(notes)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _assert_no_metadata_drift(conn: psycopg.Connection, template: RosterSourceTemplate) -> None:
    existing_id = select_data_source_id(conn, "civics", template.jurisdiction, template.name)
    if existing_id is None:
        return

    existing = select_data_source(conn, existing_id)
    if existing is None:
        raise RuntimeError(f"Unable to load existing data_source row for id={existing_id}")

    existing_notes = _decode_notes(existing.notes)
    expected_notes = template.notes_payload

    needs_repair = (
        existing.source_url != template.source_url
        or existing.source_format != "html"
        or existing.update_frequency != template.cadence
        or existing_notes != expected_notes
    )
    if not needs_repair:
        return

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.data_source
            SET source_url = %s,
                source_format = 'html',
                update_frequency = %s,
                notes = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (template.source_url, template.cadence, template.notes_json, existing_id),
        )


def register_roster_pilot_sources(conn: psycopg.Connection) -> list[UUID]:
    source_ids: list[UUID] = []
    for template in list_roster_source_templates():
        _assert_no_metadata_drift(conn, template)
        source_ids.append(ensure_data_source(conn, template.as_data_source()))
    return source_ids


def _build_argument_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Register civics roster sources in core.data_source")


def main(argv: list[str] | None = None) -> int:
    _build_argument_parser().parse_args(argv)
    connection: psycopg.Connection | None = None

    try:
        connection = get_connection()
        source_ids = register_roster_pilot_sources(connection)
        connection.commit()
    except Exception as error:  # noqa: BLE001
        if connection is not None and connection.info.transaction_status != TransactionStatus.IDLE:
            connection.rollback()
        print(f"Roster pilot source registration failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    print(f"Roster pilot source registration complete: {len(source_ids)} rows ensured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
