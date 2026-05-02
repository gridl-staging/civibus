from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.types.python.models import DataSource, RefreshRun, SourceRecord, compute_record_hash


class TestDataSourceModel:
    def test_data_source_creation_minimum_fields_uses_defaults(self) -> None:
        data_source = DataSource(
            domain="campaign_finance",
            name="FEC Schedule A API",
            source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
        )

        assert isinstance(data_source.id, UUID)
        assert data_source.domain == "campaign_finance"
        assert data_source.name == "FEC Schedule A API"
        assert data_source.source_url == "https://api.open.fec.gov/v1/schedules/schedule_a/"
        assert data_source.jurisdiction is None
        assert data_source.source_format is None
        assert data_source.license is None
        assert data_source.update_frequency is None
        assert data_source.last_pull_at is None
        assert data_source.last_pull_status is None
        assert data_source.record_count is None
        assert data_source.notes is None
        assert isinstance(data_source.created_at, datetime)
        assert isinstance(data_source.updated_at, datetime)
        assert data_source.created_at.tzinfo is not None
        assert data_source.updated_at.tzinfo is not None

    def test_data_source_model_dump_round_trip_and_json_mode(self) -> None:
        original = DataSource(
            domain="campaign_finance",
            jurisdiction="federal/fec",
            name="FEC Schedule A API",
            source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
            source_format="api",
            license="public_domain",
            update_frequency="continuous",
            last_pull_at=datetime(2026, 3, 13, 23, 45, tzinfo=timezone.utc),
            last_pull_status="success",
            record_count=120_000,
            notes="Primary ingest source",
        )

        dumped = original.model_dump()
        recreated = DataSource(**dumped)

        assert recreated == original

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)
        assert isinstance(json_dumped["last_pull_at"], str)


class TestSourceRecordModel:
    def test_source_record_creation_minimum_fields_uses_defaults(self) -> None:
        source_record = SourceRecord(
            data_source_id=uuid4(),
            raw_fields={"transaction_id": "A1", "amount": 2500},
            pull_date=datetime(2026, 3, 13, 18, 0, tzinfo=timezone.utc),
        )

        assert isinstance(source_record.id, UUID)
        assert source_record.source_record_key is None
        assert source_record.source_url is None
        assert source_record.record_hash is None
        assert source_record.superseded_by is None
        assert isinstance(source_record.created_at, datetime)
        assert source_record.created_at.tzinfo is not None

    def test_compute_record_hash_uses_canonical_json(self) -> None:
        ordered_raw_fields = {
            "amount": 1000,
            "donor": {"first": "Pat", "last": "Lee"},
            "tags": ["high-dollar", "individual"],
        }
        reordered_raw_fields = {
            "tags": ["high-dollar", "individual"],
            "donor": {"last": "Lee", "first": "Pat"},
            "amount": 1000,
        }

        expected_hash = "832b3f6b2a1d7b009795e6a64e0adf2bd5bcdfaaef2042c94d6988a8c90da5df"

        assert compute_record_hash(ordered_raw_fields) == expected_hash
        assert compute_record_hash(reordered_raw_fields) == expected_hash

    def test_source_record_model_dump_round_trip_preserves_nested_raw_fields(self) -> None:
        original = SourceRecord(
            data_source_id=uuid4(),
            source_record_key="2026-03-13-A1",
            source_url="https://example.gov/records/A1",
            raw_fields={
                "meta": {"batch": "2026-03-13", "version": 2},
                "amount": 2500.75,
                "flags": ["amended", "verified"],
            },
            pull_date=datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc),
            record_hash="abc123",
            superseded_by=uuid4(),
        )

        dumped = original.model_dump()
        recreated = SourceRecord(**dumped)

        assert recreated == original
        assert isinstance(dumped["raw_fields"], dict)

    @pytest.mark.parametrize(
        ("raw_fields", "expected_message"),
        [
            (
                {"reported_at": datetime(2026, 3, 13, 8, 30, tzinfo=timezone.utc)},
                "unsupported JSON value type datetime",
            ),
            ({"flags": {"amended", "verified"}}, "unsupported JSON value type set"),
            ({"amounts": (100, 200)}, "unsupported JSON value type tuple"),
            ({"amount": float("nan")}, "finite JSON numbers"),
            ({"amount": float("inf")}, "finite JSON numbers"),
        ],
    )
    def test_source_record_rejects_non_json_safe_raw_fields(
        self,
        raw_fields: dict[str, object],
        expected_message: str,
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SourceRecord(
                data_source_id=uuid4(),
                raw_fields=raw_fields,
                pull_date=datetime(2026, 3, 13, 18, 0, tzinfo=timezone.utc),
            )

        assert expected_message in str(exc_info.value)

    @pytest.mark.parametrize(
        "raw_fields",
        [
            {"reported_at": datetime(2026, 3, 13, 8, 30, tzinfo=timezone.utc)},
            {"amount": float("nan")},
        ],
    )
    def test_compute_record_hash_rejects_non_json_safe_raw_fields(self, raw_fields: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            compute_record_hash(raw_fields)


class TestRefreshRunModel:
    def test_refresh_run_round_trip_preserves_all_fields(self) -> None:
        original = RefreshRun(
            job_key="state-co-contributions",
            domain="campaign_finance",
            jurisdiction="state/CO",
            data_source_names=["TRACER Bulk Download - Contributions"],
            pull_status="degraded",
            started_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 24, 12, 5, tzinfo=timezone.utc),
            inserted_count=80,
            skipped_count=4,
            quarantined_count=1,
            superseded_count=0,
            error_count=0,
            metadata_updates=1,
            message="Refresh job completed below historical median",
        )

        dumped = original.model_dump()
        recreated = RefreshRun(**dumped)

        assert recreated == original

    def test_refresh_run_rejects_unknown_pull_status(self) -> None:
        with pytest.raises(ValidationError, match="Input should be"):
            RefreshRun(
                job_key="state-co-contributions",
                domain="campaign_finance",
                jurisdiction="state/CO",
                pull_status="partial",
                started_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 4, 24, 12, 5, tzinfo=timezone.utc),
                message="bad",
            )
