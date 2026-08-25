"""Red-first contract tests for the projection envelope and mutually exclusive outcomes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import inf, nan

import pytest
from pydantic import TypeAdapter, ValidationError

from domains.campaign_finance.coverage.status.models import (
    MISSING_OBSERVATION_REASON,
    NOT_APPLICABLE,
    UNKNOWN,
    FieldProvenance,
    ProjectedField,
    ProjectionOutcome,
    ProjectionReport,
    Refusal,
    UnknownFact,
    build_projected_field,
    refuse,
)

_CALCULATED_AT = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _provenance(
    *,
    owner: str = "o",
    read_path: str = "p",
    origin: str = "direct",
    execution_origin: str = UNKNOWN,
) -> FieldProvenance:
    return FieldProvenance(owner=owner, read_path=read_path, origin=origin, execution_origin=execution_origin)


def _outcome_adapter() -> TypeAdapter[ProjectionOutcome]:
    return TypeAdapter(ProjectionOutcome)


def test_report_calculated_at_requires_timezone_aware_utc() -> None:
    report = ProjectionReport(calculated_at=_CALCULATED_AT)
    assert report.calculated_at == _CALCULATED_AT

    with pytest.raises(ValidationError, match="timezone-aware"):
        ProjectionReport(calculated_at=datetime(2026, 8, 22, 12, 0, 0))


def test_report_normalizes_non_utc_offset_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    report = ProjectionReport(calculated_at=datetime(2026, 8, 22, 8, 0, 0, tzinfo=eastern))
    assert report.calculated_at == _CALCULATED_AT


def test_datetime_backed_field_pins_serialized_contract_and_round_trips() -> None:
    observed = datetime(2026, 8, 20, 6, 0, 0, tzinfo=timezone.utc)
    field = build_projected_field(
        value="California",
        provenance=_provenance(owner="coverage-registry", read_path="registry.py::CoverageRegistryRow"),
        calculated_at=_CALCULATED_AT,
        source_observed_at=observed,
    )

    # age hand-calculated: 2026-08-22T12:00Z - 2026-08-20T06:00Z = 2 days 6 hours.
    assert field.age == timedelta(days=2, hours=6)
    assert field.model_dump(mode="json") == {
        "status": "value",
        "value": "California",
        "owner": "coverage-registry",
        "read_path": "registry.py::CoverageRegistryRow",
        "origin": "direct",
        "execution_origin": UNKNOWN,
        "source_observed_at": "2026-08-20T06:00:00Z",
        "age": "P2DT6H",
        "observation_unknown_reason": None,
    }
    assert ProjectedField.model_validate(field.model_dump()) == field
    # JSON round-trip must also preserve the datetime arm exactly.
    assert ProjectedField.model_validate(field.model_dump(mode="json")) == field


def test_midnight_utc_datetime_observation_round_trips_without_degrading_to_date() -> None:
    # A datetime observation at exactly 00:00 UTC serializes to "...T00:00:00Z"; the
    # union must route that string back to the datetime arm, not lax-coerce it to a bare
    # date and silently drop the time and tzinfo.
    observed = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
    field = build_projected_field(
        value="California",
        provenance=_provenance(owner="coverage-registry", read_path="registry.py::CoverageRegistryRow"),
        calculated_at=_CALCULATED_AT,
        source_observed_at=observed,
    )

    assert isinstance(field.source_observed_at, datetime)
    assert field.model_dump(mode="json")["source_observed_at"] == "2026-08-20T00:00:00Z"

    round_tripped = ProjectedField.model_validate(field.model_dump(mode="json"))
    assert isinstance(round_tripped.source_observed_at, datetime)
    assert round_tripped.source_observed_at == observed
    assert round_tripped == field


def test_projected_field_defaults_execution_origin_to_unknown() -> None:
    field = build_projected_field(
        value="latest operational proof absent",
        provenance=_provenance(owner="core.refresh_run", read_path="core.refresh_run.completed_at"),
        calculated_at=_CALCULATED_AT,
        source_observed_at=None,
    )

    assert field.execution_origin == UNKNOWN
    assert field.model_dump(mode="json")["execution_origin"] == UNKNOWN


def test_projected_field_carries_owner_supplied_execution_origin() -> None:
    field = build_projected_field(
        value="scheduled",
        provenance=_provenance(
            owner="core.refresh_run",
            read_path="core.refresh_run.trigger",
            execution_origin="scheduled",
        ),
        calculated_at=_CALCULATED_AT,
        source_observed_at=NOT_APPLICABLE,
    )

    assert field.execution_origin == "scheduled"
    assert field.model_dump(mode="json")["execution_origin"] == "scheduled"


def test_date_backed_field_age_is_hand_calculated_from_calculated_at() -> None:
    field = build_projected_field(
        value="launch-support candidate",
        provenance=_provenance(
            owner="coverage-registry",
            read_path="registry.py::CoverageRegistryRow.evidence_date",
            origin="inherited",
        ),
        calculated_at=_CALCULATED_AT,
        source_observed_at=date(2026, 8, 12),
    )

    # 2026-08-22T12:00Z - 2026-08-12T00:00Z = 10 days 12 hours.
    assert field.source_observed_at == date(2026, 8, 12)
    assert field.age == timedelta(days=10, hours=12)
    # A date-backed observation must stay a date across a JSON round-trip, not widen to
    # a naive midnight datetime.
    round_tripped = ProjectedField.model_validate(field.model_dump(mode="json"))
    assert round_tripped.source_observed_at == date(2026, 8, 12)
    assert round_tripped == field


def test_structural_field_uses_not_applicable_without_fabricated_timestamp() -> None:
    field = build_projected_field(
        value=True,
        provenance=_provenance(owner="core/refresh/runner.py", read_path="core/refresh/runner.py::RefreshJob"),
        calculated_at=_CALCULATED_AT,
        source_observed_at=NOT_APPLICABLE,
    )

    assert field.source_observed_at == NOT_APPLICABLE
    assert field.age == NOT_APPLICABLE
    assert field.observation_unknown_reason is None


def test_missing_observation_time_on_freshness_fact_is_unknown_with_exact_reason() -> None:
    field = build_projected_field(
        value="2026 cycle",
        provenance=_provenance(
            owner="lifecycle.py",
            read_path="lifecycle.py::ImplementedRegionLifecycleRegistry.updated_at",
        ),
        calculated_at=_CALCULATED_AT,
        source_observed_at=None,
    )

    assert field.source_observed_at == UNKNOWN
    assert field.age == UNKNOWN
    assert field.observation_unknown_reason == MISSING_OBSERVATION_REASON
    assert MISSING_OBSERVATION_REASON == "missing observation time"


def test_projected_field_rejects_structural_state_with_real_age() -> None:
    with pytest.raises(ValidationError):
        ProjectedField(
            value="x",
            owner="o",
            read_path="p",
            origin="direct",
            source_observed_at=NOT_APPLICABLE,
            age=timedelta(days=1),
        )


def test_projected_field_rejects_unknown_observation_without_reason() -> None:
    with pytest.raises(ValidationError):
        ProjectedField(
            value="x",
            owner="o",
            read_path="p",
            origin="direct",
            source_observed_at=UNKNOWN,
            age=UNKNOWN,
            observation_unknown_reason=None,
        )


def test_projected_field_rejects_datetime_observation_with_sentinel_age() -> None:
    with pytest.raises(ValidationError):
        ProjectedField(
            value="x",
            owner="o",
            read_path="p",
            origin="direct",
            source_observed_at=datetime(2026, 8, 20, 6, 0, 0, tzinfo=timezone.utc),
            age=NOT_APPLICABLE,
        )


def test_projected_field_rejects_unknown_origin() -> None:
    with pytest.raises(ValidationError):
        build_projected_field(
            value="x",
            provenance=_provenance(origin="fabricated"),
            calculated_at=_CALCULATED_AT,
            source_observed_at=NOT_APPLICABLE,
        )


def test_unknown_fact_requires_non_empty_reason() -> None:
    fact = UnknownFact(reason="coverage-registry evidence_date absent")
    assert fact.status == "unknown"

    with pytest.raises(ValidationError, match="reason"):
        UnknownFact(reason="   ")


def test_refusal_carries_scope_reason_and_canonical_owner() -> None:
    refusal = refuse(
        scope="LA",
        reason="missing coverage-registry row for 'LA'",
        canonical_owner="coverage-registry",
    )
    assert isinstance(refusal, Refusal)
    assert refusal.status == "refuse"
    assert (refusal.scope, refusal.reason, refusal.canonical_owner) == (
        "LA",
        "missing coverage-registry row for 'LA'",
        "coverage-registry",
    )

    with pytest.raises(ValidationError):
        refuse(scope="LA", reason=" ", canonical_owner="coverage-registry")


def test_projection_outcome_discriminates_all_three_classes() -> None:
    adapter = _outcome_adapter()
    value_field = build_projected_field(
        value="v",
        provenance=_provenance(),
        calculated_at=_CALCULATED_AT,
        source_observed_at=NOT_APPLICABLE,
    )

    assert isinstance(adapter.validate_python(value_field.model_dump()), ProjectedField)
    assert isinstance(adapter.validate_python({"status": "unknown", "reason": "absent"}), UnknownFact)
    assert isinstance(
        adapter.validate_python(
            {"status": "refuse", "scope": "LA", "reason": "boom", "canonical_owner": "coverage-registry"}
        ),
        Refusal,
    )


def test_projection_outcome_rejects_value_and_refusal_hybrid() -> None:
    adapter = _outcome_adapter()
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "status": "value",
                "value": "v",
                "owner": "o",
                "read_path": "p",
                "origin": "direct",
                "source_observed_at": NOT_APPLICABLE,
                "age": NOT_APPLICABLE,
                "canonical_owner": "coverage-registry",
            }
        )


def test_projection_outcome_rejects_unknown_and_value_hybrid() -> None:
    adapter = _outcome_adapter()
    with pytest.raises(ValidationError):
        adapter.validate_python({"status": "unknown", "reason": "absent", "value": "v"})


def test_projected_field_rejects_naive_datetime_observation() -> None:
    # The builder enforces awareness; direct construction must not be a looser back door.
    with pytest.raises(ValidationError, match="timezone-aware"):
        ProjectedField(
            value="x",
            owner="o",
            read_path="p",
            origin="direct",
            source_observed_at=datetime(2026, 8, 20, 6, 0, 0),
            age=timedelta(days=1),
        )


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_field_provenance_rejects_blank_owner(blank: str) -> None:
    with pytest.raises(ValidationError):
        FieldProvenance(owner=blank, read_path="p", origin="direct")


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_field_provenance_rejects_blank_read_path(blank: str) -> None:
    with pytest.raises(ValidationError):
        FieldProvenance(owner="o", read_path=blank, origin="direct")


def test_projected_field_rejects_blank_owner_on_serialized_contract() -> None:
    # A projected value must never publish provenance-free output: a blank owner in a
    # serialized ProjectedField is rejected, not accepted as a status="value" field.
    adapter = _outcome_adapter()
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "status": "value",
                "value": "v",
                "owner": "   ",
                "read_path": "p",
                "origin": "direct",
                "source_observed_at": NOT_APPLICABLE,
                "age": NOT_APPLICABLE,
            }
        )


def test_projected_field_rejects_blank_read_path_on_serialized_contract() -> None:
    with pytest.raises(ValidationError):
        ProjectedField(
            value="v",
            owner="o",
            read_path="  ",
            origin="direct",
            source_observed_at=NOT_APPLICABLE,
            age=NOT_APPLICABLE,
        )


def test_projected_field_rejects_opaque_non_serializable_value() -> None:
    # An opaque Python object crashes model_dump_json(); it must be rejected at
    # construction, not silently published and then blow up at serialization time.
    with pytest.raises(ValidationError):
        build_projected_field(
            value=object(),
            provenance=_provenance(),
            calculated_at=_CALCULATED_AT,
            source_observed_at=NOT_APPLICABLE,
        )


def test_projected_field_accepts_json_serializable_values_and_dumps() -> None:
    # The accepted value set stays JSON-serializable, including nested structures.
    field = build_projected_field(
        value={"seats": 543, "vacant": [1, 2], "ready": True, "note": None},
        provenance=_provenance(),
        calculated_at=_CALCULATED_AT,
        source_observed_at=NOT_APPLICABLE,
    )
    assert field.model_dump_json()  # must not raise


@pytest.mark.parametrize(
    ("temporal_value", "serialized_value"),
    [
        (date(2026, 8, 22), "2026-08-22"),
        (datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc), "2026-08-22T00:00:00Z"),
    ],
)
def test_temporal_projected_value_has_stable_json_round_trip(
    temporal_value: date | datetime,
    serialized_value: str,
) -> None:
    field = build_projected_field(
        value={"observed_at": temporal_value},
        provenance=_provenance(),
        calculated_at=_CALCULATED_AT,
        source_observed_at=NOT_APPLICABLE,
    )

    assert field.value == {"observed_at": serialized_value}
    assert field.model_dump(mode="json")["value"] == {"observed_at": serialized_value}
    assert ProjectedField.model_validate(field.model_dump(mode="json")) == field


@pytest.mark.parametrize("nonfinite_value", [nan, inf, -inf])
def test_projected_field_rejects_nonfinite_float_before_json_null_coercion(nonfinite_value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        build_projected_field(
            value={"measurement": [nonfinite_value]},
            provenance=_provenance(),
            calculated_at=_CALCULATED_AT,
            source_observed_at=NOT_APPLICABLE,
        )


def test_report_project_field_binds_calculated_at_to_field_age() -> None:
    report = ProjectionReport(calculated_at=_CALCULATED_AT)
    field = report.project_field(
        value="California",
        provenance=_provenance(owner="coverage-registry", read_path="registry.py"),
        source_observed_at=date(2026, 8, 12),
    )

    # age computed against the report's own calculated_at, not a separately supplied one.
    assert field.age == timedelta(days=10, hours=12)
