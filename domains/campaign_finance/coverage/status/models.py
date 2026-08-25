"""Read-only projection envelope and mutually exclusive outcomes.

This module is the single owner of the ephemeral projection contracts shared by the
future ``product-status``, ``region-status``, and ``coverage-status`` views (see
``docs/reference/specs/campaign-finance-region-lifecycle.md`` "Derived Status Views").

It is value-agnostic and side-effect-free: it wraps caller-supplied canonical facts
with exact provenance and one age-calculation seam. It never loads files, queries a
database, calls a network service, caches results, infers ``execution_origin``, or
introduces freshness thresholds not owned by the source contract.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Annotated, Final, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

OriginLiteral = Literal["direct", "inherited"]


def _require_non_empty_provenance(value: str) -> str:
    if not value.strip():
        raise ValueError("provenance identifiers (owner, read_path) must be non-empty")
    return value


# Single shared seam for the non-empty owner/read_path provenance rule, reused by both
# ``FieldProvenance`` and the serialized ``ProjectedField`` contract so a projected value
# can never publish provenance-free output.
ProvenanceIdentifier = Annotated[str, AfterValidator(_require_non_empty_provenance)]

# The closed set of value shapes the projection layer accepts. Every accepted projected
# fact must be JSON-serializable so a view can publish it via ``model_dump_json()``;
# opaque Python objects (which crash serialization) are rejected at construction, not at
# publish time. Temporal types later views carry (``date``/``datetime``) are included.
type JsonSerializableValue = (
    str | bool | int | float | None | date | datetime | list[JsonSerializableValue] | dict[str, JsonSerializableValue]
)


def _normalize_json_value(value: JsonSerializableValue) -> JsonSerializableValue:
    """Return the stable JSON representation of a projected value."""

    if isinstance(value, datetime):
        serialized = value.isoformat()
        return f"{serialized[:-6]}Z" if serialized.endswith("+00:00") else serialized
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("projected float values must be finite")
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_value(item) for key, item in value.items()}
    return value


# Sentinels for the freshness portion of a projected field. ``not_applicable`` marks a
# structural / code-derived fact that carries no observation time; ``UNKNOWN`` marks a
# freshness-bearing fact whose observation time is absent (never treated as "healthy").
NOT_APPLICABLE: Final[str] = "not_applicable"
UNKNOWN: Final[str] = "UNKNOWN"
MISSING_OBSERVATION_REASON: Final[str] = "missing observation time"

_NotApplicable = Literal["not_applicable"]
_Unknown = Literal["UNKNOWN"]

# What a caller may hand the age seam as the source observation time.
ObservationInput = Union[datetime, date, _NotApplicable, None]


class StatusProjectionModel(BaseModel):
    """Strict base: no undeclared fields may cross the projection boundary."""

    model_config = ConfigDict(extra="forbid")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calculated_at must be timezone-aware")
    return value.astimezone(timezone.utc)


class ProjectionReport(StatusProjectionModel):
    """Report-level envelope carrying the one UTC report time a view was computed at.

    ``calculated_at`` is a report timestamp only; it is never a source observation time.
    """

    calculated_at: datetime

    @model_validator(mode="after")
    def _normalize_calculated_at(self) -> "ProjectionReport":
        object.__setattr__(self, "calculated_at", _require_utc(self.calculated_at))
        return self

    def project_field(
        self,
        *,
        value: "JsonSerializableValue",
        provenance: "FieldProvenance",
        source_observed_at: "ObservationInput",
    ) -> "ProjectedField":
        """Project one field, computing its age against this report's ``calculated_at``.

        This binds the report time to every field it produces, so a view cannot compute a
        field's age against a different instant than the report it publishes. It is the
        report-bound entry point to the single age-calculation seam.
        """

        return build_projected_field(
            value=value,
            provenance=provenance,
            calculated_at=self.calculated_at,
            source_observed_at=source_observed_at,
        )


class FieldProvenance(StatusProjectionModel):
    """Where one projected fact came from: its canonical owner, read path, and origin.

    ``execution_origin`` defaults to ``UNKNOWN``. A caller may forward only a value an
    existing canonical owner supplies for that exact fact and must never derive or infer
    one; the projection layer has no execution-origin source of its own.
    """

    owner: ProvenanceIdentifier
    read_path: ProvenanceIdentifier
    origin: OriginLiteral
    execution_origin: str = UNKNOWN


class ProjectedField(StatusProjectionModel):
    """The ``value`` outcome: one canonical fact wrapped with provenance and age.

    ``source_observed_at`` / ``age`` are populated only when the owner supplies an
    observation timestamp. A structural fact carries ``not_applicable``; a
    freshness-bearing fact with no observation time carries ``UNKNOWN`` with
    ``observation_unknown_reason``.
    """

    status: Literal["value"] = "value"
    value: JsonSerializableValue
    owner: ProvenanceIdentifier
    read_path: ProvenanceIdentifier
    origin: OriginLiteral
    execution_origin: str = UNKNOWN
    source_observed_at: date | datetime | _NotApplicable | _Unknown
    age: timedelta | _NotApplicable | _Unknown
    observation_unknown_reason: str | None = None

    @field_validator("value", mode="after")
    @classmethod
    def _normalize_value_for_json_round_trip(cls, value: JsonSerializableValue) -> JsonSerializableValue:
        return _normalize_json_value(value)

    @field_validator("source_observed_at", mode="before")
    @classmethod
    def _route_serialized_observation(cls, value: object) -> object:
        """Route a serialized observation string to the correct ``date``/``datetime`` arm.

        A serialized ``date`` and a serialized ``datetime`` are both strings, so union
        ordering alone is ambiguous: a lax pass would coerce a midnight datetime
        (``...T00:00:00Z``) to a bare ``date`` and drop its time and tzinfo. A string
        carrying a time component parses to the ``datetime`` arm; a bare ``YYYY-MM-DD``
        parses to the ``date`` arm. Real ``date``/``datetime`` objects and the
        ``not_applicable`` / ``UNKNOWN`` sentinels pass through untouched.
        """

        if not isinstance(value, str) or value in (NOT_APPLICABLE, UNKNOWN):
            return value
        has_time_component = "T" in value or " " in value
        try:
            return datetime.fromisoformat(value) if has_time_component else date.fromisoformat(value)
        except ValueError:
            return value

    @model_validator(mode="after")
    def _validate_freshness_consistency(self) -> "ProjectedField":
        if not self.execution_origin.strip():
            raise ValueError("execution_origin must be non-empty")
        observed = self.source_observed_at
        if observed == NOT_APPLICABLE:
            if self.age != NOT_APPLICABLE:
                raise ValueError("age must be not_applicable when source_observed_at is not_applicable")
            if self.observation_unknown_reason is not None:
                raise ValueError("observation_unknown_reason must be null for a structural fact")
        elif observed == UNKNOWN:
            if self.age != UNKNOWN:
                raise ValueError("age must be UNKNOWN when source_observed_at is UNKNOWN")
            if not (self.observation_unknown_reason or "").strip():
                raise ValueError("observation_unknown_reason is required when source_observed_at is UNKNOWN")
        else:
            if isinstance(observed, datetime) and (observed.tzinfo is None or observed.utcoffset() is None):
                raise ValueError("source_observed_at datetime must be timezone-aware")
            if not isinstance(self.age, timedelta):
                raise ValueError("age must be a timedelta when source_observed_at is an observation time")
            if self.observation_unknown_reason is not None:
                raise ValueError("observation_unknown_reason must be null when an observation time is present")
        return self


class UnknownFact(StatusProjectionModel):
    """The ``UNKNOWN`` outcome: an optional / applicability-dependent fact is absent."""

    status: Literal["unknown"] = "unknown"
    reason: str

    @model_validator(mode="after")
    def _validate_reason(self) -> "UnknownFact":
        if not self.reason.strip():
            raise ValueError("UnknownFact.reason must be non-empty")
        return self


class Refusal(StatusProjectionModel):
    """The ``REFUSE`` outcome: a required owner/join/invariant failed for one region/view.

    A refusal is loud and scoped; it names the canonical owner to correct and never
    emits the disputed value alongside it.
    """

    status: Literal["refuse"] = "refuse"
    scope: str
    reason: str
    canonical_owner: str

    @model_validator(mode="after")
    def _validate_non_empty(self) -> "Refusal":
        for field_name in ("scope", "reason", "canonical_owner"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Refusal.{field_name} must be non-empty")
        return self


# Mutually exclusive projection outcome. ``extra="forbid"`` on each arm makes hybrid
# states (a value carrying a refusal reason, an unknown carrying a value) unrepresentable.
ProjectionOutcome = Annotated[
    Union[ProjectedField, UnknownFact, Refusal],
    Field(discriminator="status"),
]


def _to_aware_datetime(observed: datetime | date) -> datetime:
    if isinstance(observed, datetime):
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observation datetime must be timezone-aware")
        return observed.astimezone(timezone.utc)
    return datetime.combine(observed, time.min, tzinfo=timezone.utc)


def build_projected_field(
    *,
    value: JsonSerializableValue,
    provenance: FieldProvenance,
    calculated_at: datetime,
    source_observed_at: ObservationInput,
) -> ProjectedField:
    """Construct a projected field, computing ``age`` against ``calculated_at``.

    This is the single age-calculation seam every view reuses. ``provenance`` carries the
    owner, read path, origin, and any owner-supplied ``execution_origin``.
    ``source_observed_at``: ``NOT_APPLICABLE`` for a structural fact, a ``date``/
    ``datetime`` for an observed fact, or ``None`` for a freshness-bearing fact whose
    observation time is missing.
    """

    report_time = _require_utc(calculated_at)
    if source_observed_at == NOT_APPLICABLE:
        observation: datetime | date | str = NOT_APPLICABLE
        age: timedelta | str = NOT_APPLICABLE
        reason: str | None = None
    elif source_observed_at is None:
        observation = UNKNOWN
        age = UNKNOWN
        reason = MISSING_OBSERVATION_REASON
    else:
        observation = source_observed_at
        age = report_time - _to_aware_datetime(source_observed_at)
        reason = None
    return ProjectedField(
        value=value,
        owner=provenance.owner,
        read_path=provenance.read_path,
        origin=provenance.origin,
        execution_origin=provenance.execution_origin,
        source_observed_at=observation,
        age=age,
        observation_unknown_reason=reason,
    )


def refuse(*, scope: str, reason: str, canonical_owner: str) -> Refusal:
    """Build a scoped refusal that names the canonical owner to correct."""

    return Refusal(scope=scope, reason=reason, canonical_owner=canonical_owner)
