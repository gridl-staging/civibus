"""Fail-closed translation from municipality config to canonical geography.

The resolver consumes a read projection supplied by ``core.jurisdiction``.  It
does not store city facts, read compatibility ``fips`` values, infer identity
from names, or project coverage, routes, or public-selection state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Literal, TypeAlias
from uuid import UUID

import psycopg
from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from domains.campaign_finance.jurisdictions.config_schema import (
    ConfigJurisdictionIdentity,
    JurisdictionIdentity,
)


GeographyIdentifierKind: TypeAlias = Literal[
    "state_fips",
    "place_geoid",
    "county_geoid",
]
CanonicalJurisdictionKind: TypeAlias = Literal[
    "federal",
    "state",
    "county",
    "municipality",
    "consolidated_city_county",
    "school_district",
    "special_district",
]
ResolvedMunicipalityKind: TypeAlias = Literal[
    "municipality",
    "consolidated_city_county",
]

_IDENTIFIER_LENGTHS: dict[GeographyIdentifierKind, int] = {
    "state_fips": 2,
    "county_geoid": 5,
    "place_geoid": 7,
}


class MunicipalityGeographyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GeographyIdentifier(MunicipalityGeographyModel):
    """One explicit native identifier owned by ``core.jurisdiction``."""

    namespace: Literal["core.jurisdiction"]
    kind: GeographyIdentifierKind
    value: StrictStr

    @model_validator(mode="after")
    def _validate_native_identifier(self) -> "GeographyIdentifier":
        expected_length = _IDENTIFIER_LENGTHS[self.kind]
        if len(self.value) != expected_length or not self.value.isascii() or not self.value.isdigit():
            raise ValueError(f"{self.kind} must contain exactly {expected_length} ASCII digits")
        return self


class CanonicalJurisdictionSubject(MunicipalityGeographyModel):
    """Narrow read projection of one canonical ``core.jurisdiction`` subject."""

    id: UUID
    name: StrictStr
    jurisdiction_kind: CanonicalJurisdictionKind
    parent_id: UUID | None
    state: StrictStr | None
    identifiers: tuple[GeographyIdentifier, ...]


class ResolvedMunicipalityGeography(MunicipalityGeographyModel):
    """Geography-only resolution; deliberately excludes product authority."""

    config_identity: ConfigJurisdictionIdentity
    jurisdiction_id: UUID
    name: StrictStr
    geographic_kind: ResolvedMunicipalityKind
    state: StrictStr
    place_geoid: StrictStr
    county_geoid: StrictStr | None


class MunicipalityGeographyResolutionError(ValueError):
    """Base class for auditable fail-closed municipality translation."""


class MissingGeographyMatchError(MunicipalityGeographyResolutionError):
    pass


class AmbiguousGeographyMatchError(MunicipalityGeographyResolutionError):
    pass


class WrongGeographyIdentifierKindError(MunicipalityGeographyResolutionError):
    pass


class GeographySubjectKindError(MunicipalityGeographyResolutionError):
    pass


class GeographyIdentityContradictionError(MunicipalityGeographyResolutionError):
    pass


class GeographyParentContradictionError(MunicipalityGeographyResolutionError):
    pass


class ConsolidatedGeographyEvidenceError(MunicipalityGeographyResolutionError):
    pass


_CANONICAL_JURISDICTION_PROJECTION_SQL = """
WITH target AS (
    SELECT
        id,
        name,
        jurisdiction_type,
        parent_id,
        state,
        state_fips,
        county_geoid,
        place_geoid
    FROM core.jurisdiction
    WHERE (%(kind)s = 'place_geoid' AND place_geoid = %(value)s)
       OR (%(kind)s = 'county_geoid' AND county_geoid = %(value)s)
),
projection AS (
    SELECT *
    FROM target

    UNION

    SELECT
        parent.id,
        parent.name,
        parent.jurisdiction_type,
        parent.parent_id,
        parent.state,
        parent.state_fips,
        parent.county_geoid,
        parent.place_geoid
    FROM core.jurisdiction AS parent
    JOIN target AS target_subject
      ON parent.id = target_subject.parent_id

    UNION

    SELECT
        grandparent.id,
        grandparent.name,
        grandparent.jurisdiction_type,
        grandparent.parent_id,
        grandparent.state,
        grandparent.state_fips,
        grandparent.county_geoid,
        grandparent.place_geoid
    FROM core.jurisdiction AS grandparent
    JOIN core.jurisdiction AS parent
      ON grandparent.id = parent.parent_id
    JOIN target AS target_subject
      ON parent.id = target_subject.parent_id
)
SELECT
    id,
    name,
    CASE
        WHEN jurisdiction_type = 'municipality'
         AND place_geoid IS NOT NULL
         AND county_geoid IS NOT NULL
        THEN 'consolidated_city_county'
        ELSE jurisdiction_type
    END AS jurisdiction_kind,
    parent_id,
    state,
    state_fips,
    county_geoid,
    place_geoid
FROM projection
ORDER BY id
"""


def project_canonical_jurisdiction_subjects(
    conn: psycopg.Connection,
    *,
    reference: GeographyIdentifier,
) -> tuple[CanonicalJurisdictionSubject, ...]:
    """Read one typed municipality subject and at most two ancestors."""

    if reference.kind not in {"place_geoid", "county_geoid"}:
        raise WrongGeographyIdentifierKindError(f"municipality geography cannot project from {reference.kind}")

    with conn.cursor() as cursor:
        cursor.execute(
            _CANONICAL_JURISDICTION_PROJECTION_SQL,
            {"kind": reference.kind, "value": reference.value},
        )
        rows = cursor.fetchall()

    subjects: list[CanonicalJurisdictionSubject] = []
    for row in rows:
        identifiers = tuple(
            GeographyIdentifier(
                namespace="core.jurisdiction",
                kind=kind,
                value=row[column_index],
            )
            for kind, column_index in (
                ("state_fips", 5),
                ("county_geoid", 6),
                ("place_geoid", 7),
            )
            if row[column_index] is not None
        )
        subjects.append(
            CanonicalJurisdictionSubject(
                id=row[0],
                name=row[1],
                jurisdiction_kind=row[2],
                parent_id=row[3],
                state=row[4],
                identifiers=identifiers,
            )
        )
    return tuple(subjects)


def _format_reference(reference: GeographyIdentifier) -> str:
    return f"({reference.namespace}, {reference.kind}, {reference.value})"


def _identifier_values(
    subject: CanonicalJurisdictionSubject,
    kind: GeographyIdentifierKind,
) -> tuple[str, ...]:
    return tuple(
        identifier.value
        for identifier in subject.identifiers
        if identifier.namespace == "core.jurisdiction" and identifier.kind == kind
    )


def _require_only_identifier_kinds(
    subject: CanonicalJurisdictionSubject,
    allowed_kinds: set[GeographyIdentifierKind],
) -> None:
    unexpected_kinds = sorted({identifier.kind for identifier in subject.identifiers} - allowed_kinds)
    if unexpected_kinds:
        raise WrongGeographyIdentifierKindError(
            f"{subject.jurisdiction_kind} subject {subject.id} has unexpected identifier kind(s): "
            + ", ".join(unexpected_kinds)
        )


def _require_one_identifier(
    subject: CanonicalJurisdictionSubject,
    kind: GeographyIdentifierKind,
    *,
    consolidation: bool,
) -> str:
    values = _identifier_values(subject, kind)
    if len(values) == 1:
        return values[0]

    if consolidation:
        raise ConsolidatedGeographyEvidenceError(
            f"consolidated_city_county subject {subject.id} must carry exactly one "
            f"{kind} on the same core.jurisdiction subject; found {len(values)}"
        )
    raise GeographySubjectKindError(
        f"municipality subject {subject.id} must carry exactly one {kind}; found {len(values)}"
    )


def _resolve_one_parent(
    *,
    subject: CanonicalJurisdictionSubject,
    canonical_subjects: tuple[CanonicalJurisdictionSubject, ...],
    seen_subject_ids: set[UUID],
) -> CanonicalJurisdictionSubject:
    if subject.parent_id in seen_subject_ids:
        raise GeographyParentContradictionError(
            f"core.jurisdiction ancestry cycle from subject {subject.id} to parent_id {subject.parent_id}"
        )

    parent_matches = tuple(
        candidate
        for candidate in canonical_subjects
        if subject.parent_id is not None and candidate.id == subject.parent_id
    )
    if len(parent_matches) != 1:
        raise GeographyParentContradictionError(
            f"core.jurisdiction subject {subject.id} parent_id {subject.parent_id} "
            f"must resolve exactly once; found {len(parent_matches)}"
        )

    parent = parent_matches[0]
    seen_subject_ids.add(parent.id)
    return parent


def _resolve_parent_state(
    *,
    subject: CanonicalJurisdictionSubject,
    config_identity: JurisdictionIdentity,
    canonical_subjects: tuple[CanonicalJurisdictionSubject, ...],
) -> tuple[str, str]:
    seen_subject_ids = {subject.id}
    parent = _resolve_one_parent(
        subject=subject,
        canonical_subjects=canonical_subjects,
        seen_subject_ids=seen_subject_ids,
    )
    county_parent: CanonicalJurisdictionSubject | None = None
    if parent.jurisdiction_kind == "county":
        county_parent = parent
        _require_only_identifier_kinds(county_parent, {"county_geoid"})
        county_geoids = _identifier_values(county_parent, "county_geoid")
        if len(county_geoids) != 1:
            raise GeographyParentContradictionError(
                f"canonical county parent {county_parent.id} must carry exactly one county_geoid; "
                f"found {len(county_geoids)}"
            )
        parent = _resolve_one_parent(
            subject=county_parent,
            canonical_subjects=canonical_subjects,
            seen_subject_ids=seen_subject_ids,
        )

    if parent.jurisdiction_kind != "state":
        raise GeographyParentContradictionError(
            f"core.jurisdiction subject {subject.id} ancestry must reach a state through at most one county; "
            f"found {parent.jurisdiction_kind}"
        )
    if parent.parent_id is not None:
        if parent.parent_id in seen_subject_ids:
            raise GeographyParentContradictionError(
                f"core.jurisdiction ancestry cycle from state ancestor {parent.id} to parent_id {parent.parent_id}"
            )
        raise GeographyParentContradictionError(
            f"canonical state ancestor {parent.id} must be terminal; found parent_id {parent.parent_id}"
        )

    _require_only_identifier_kinds(parent, {"state_fips"})
    state_fips = _identifier_values(parent, "state_fips")
    if len(state_fips) != 1:
        raise GeographyParentContradictionError(
            f"canonical state parent {parent.id} must carry exactly one state_fips; found {len(state_fips)}"
        )
    if parent.state is None:
        raise GeographyParentContradictionError(f"canonical state parent {parent.id} is missing its state code")
    if subject.state != parent.state:
        raise GeographyParentContradictionError(
            f"subject state {subject.state!r} contradicts canonical parent {parent.state!r}"
        )
    if config_identity.parent != parent.state:
        raise GeographyParentContradictionError(
            f"config parent {config_identity.parent!r} contradicts canonical parent "
            f"{parent.state!r} for core.jurisdiction subject {subject.id}"
        )

    if county_parent is not None and county_parent.state != parent.state:
        raise GeographyParentContradictionError(
            f"county state {county_parent.state!r} contradicts canonical state "
            f"{parent.state!r} for county parent {county_parent.id}"
        )
    geography_subjects = (subject,) if county_parent is None else (subject, county_parent)
    for geography_subject in geography_subjects:
        for identifier in geography_subject.identifiers:
            if identifier.kind in {"place_geoid", "county_geoid"} and not identifier.value.startswith(state_fips[0]):
                raise GeographyParentContradictionError(
                    f"{identifier.kind} {identifier.value!r} on core.jurisdiction subject "
                    f"{geography_subject.id} contradicts parent state_fips {state_fips[0]!r}"
                )
    return parent.state, state_fips[0]


def resolve_municipality_geography(
    *,
    config_identity: JurisdictionIdentity,
    reference: GeographyIdentifier,
    target_kind: ResolvedMunicipalityKind,
    canonical_subjects: Iterable[CanonicalJurisdictionSubject],
) -> ResolvedMunicipalityGeography:
    """Resolve one municipality config against typed canonical-owner records.

    ``config_identity.fips`` is intentionally never read.  Its legacy token is
    compatibility/source context, not a stable-geography join key.
    """

    if config_identity.type != "municipality":
        raise GeographySubjectKindError(
            f"config identity {config_identity.type}/{config_identity.code} is not a municipality"
        )
    if not isinstance(reference, GeographyIdentifier):
        raise WrongGeographyIdentifierKindError(
            "municipality geography requires an explicit "
            "(core.jurisdiction, identifier kind, value) reference; bare FIPS is refused"
        )
    if target_kind not in {"municipality", "consolidated_city_county"}:
        raise GeographySubjectKindError(f"unsupported municipality geography target kind {target_kind!r}")
    if reference.kind not in {"place_geoid", "county_geoid"}:
        raise WrongGeographyIdentifierKindError(f"municipality geography cannot resolve from {reference.kind}")

    subjects = tuple(canonical_subjects)
    duplicate_subject_ids = sorted(
        str(subject_id) for subject_id, count in Counter(subject.id for subject in subjects).items() if count > 1
    )
    if duplicate_subject_ids:
        raise AmbiguousGeographyMatchError(
            "duplicate core.jurisdiction subject id(s) in canonical projection: " + ", ".join(duplicate_subject_ids)
        )
    exact_matches = tuple(subject for subject in subjects if reference in subject.identifiers)
    if not exact_matches:
        value_matches = tuple(
            identifier.kind
            for subject in subjects
            for identifier in subject.identifiers
            if identifier.namespace == reference.namespace and identifier.value == reference.value
        )
        if value_matches:
            found_kinds = ", ".join(sorted(set(value_matches)))
            raise WrongGeographyIdentifierKindError(
                f"wrong kind for {_format_reference(reference)} in core.jurisdiction; "
                f"value exists only as {found_kinds}"
            )
        raise MissingGeographyMatchError(f"found 0 core.jurisdiction subjects for {_format_reference(reference)}")
    if len(exact_matches) != 1:
        raise AmbiguousGeographyMatchError(
            f"found {len(exact_matches)} core.jurisdiction subjects for {_format_reference(reference)}"
        )

    subject = exact_matches[0]
    if subject.jurisdiction_kind != target_kind:
        raise GeographySubjectKindError(
            f"core.jurisdiction subject {subject.id} does not match explicit target "
            f"kind {target_kind}; found {subject.jurisdiction_kind}"
        )
    allowed_identifier_kinds: set[GeographyIdentifierKind]
    if subject.jurisdiction_kind == "municipality":
        allowed_identifier_kinds = {"place_geoid"}
    else:
        allowed_identifier_kinds = {"place_geoid", "county_geoid"}
    _require_only_identifier_kinds(subject, allowed_identifier_kinds)
    if subject.name != config_identity.name:
        raise GeographyIdentityContradictionError(
            f"config municipality name {config_identity.name!r} contradicts "
            f"canonical subject name {subject.name!r} for {_format_reference(reference)}"
        )

    state, state_fips = _resolve_parent_state(
        subject=subject,
        config_identity=config_identity,
        canonical_subjects=subjects,
    )
    place_geoid = _require_one_identifier(
        subject,
        "place_geoid",
        consolidation=subject.jurisdiction_kind == "consolidated_city_county",
    )

    if subject.jurisdiction_kind == "municipality":
        county_identifiers = _identifier_values(subject, "county_geoid")
        if reference.kind != "place_geoid" or county_identifiers:
            raise WrongGeographyIdentifierKindError(
                f"ordinary municipality subject {subject.id} requires place_geoid and "
                "cannot resolve through a county-equivalent identifier"
            )
        county_geoid = None
    else:
        county_geoid = _require_one_identifier(
            subject,
            "county_geoid",
            consolidation=True,
        )

    duplicate_identifier_kinds = sorted(
        kind for kind, count in Counter(identifier.kind for identifier in subject.identifiers).items() if count > 1
    )
    if duplicate_identifier_kinds:
        joined_kinds = ", ".join(duplicate_identifier_kinds)
        raise GeographySubjectKindError(
            f"core.jurisdiction subject {subject.id} has duplicate typed identifiers: {joined_kinds}"
        )

    return ResolvedMunicipalityGeography(
        config_identity=config_identity.identity,
        jurisdiction_id=subject.id,
        name=subject.name,
        geographic_kind=subject.jurisdiction_kind,
        state=state,
        place_geoid=place_geoid,
        county_geoid=county_geoid,
    )


__all__ = [
    "AmbiguousGeographyMatchError",
    "CanonicalJurisdictionSubject",
    "ConsolidatedGeographyEvidenceError",
    "GeographyIdentifier",
    "GeographyIdentityContradictionError",
    "GeographyParentContradictionError",
    "GeographySubjectKindError",
    "MissingGeographyMatchError",
    "project_canonical_jurisdiction_subjects",
    "ResolvedMunicipalityGeography",
    "WrongGeographyIdentifierKindError",
    "resolve_municipality_geography",
]
