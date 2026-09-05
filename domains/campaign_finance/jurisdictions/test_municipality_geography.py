from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re
from unittest.mock import MagicMock
from uuid import UUID

import psycopg
import pytest
from pydantic import ValidationError

from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionIdentity,
    load_jurisdiction_config,
)
from domains.campaign_finance.jurisdictions.municipality_geography import (
    AmbiguousGeographyMatchError,
    CanonicalJurisdictionSubject,
    ConsolidatedGeographyEvidenceError,
    GeographyIdentifier,
    GeographyIdentityContradictionError,
    GeographyParentContradictionError,
    GeographySubjectKindError,
    MissingGeographyMatchError,
    WrongGeographyIdentifierKindError,
    project_canonical_jurisdiction_subjects,
    resolve_municipality_geography,
)


_CITIES_ROOT = Path(__file__).resolve().parent / "cities"
_CA_ID = UUID("10000000-0000-4000-8000-000000000006")
_NY_ID = UUID("10000000-0000-4000-8000-000000000036")
_PA_ID = UUID("10000000-0000-4000-8000-000000000042")
_LA_ID = UUID("20000000-0000-4000-8000-000000000001")
_NYC_ID = UUID("20000000-0000-4000-8000-000000000002")
_PHL_ID = UUID("20000000-0000-4000-8000-000000000003")
_SF_ID = UUID("20000000-0000-4000-8000-000000000004")
_LA_COUNTY_ID = UUID("30000000-0000-4000-8000-000000000037")


def _identifier(kind: str, value: str) -> GeographyIdentifier:
    return GeographyIdentifier.model_validate({"namespace": "core.jurisdiction", "kind": kind, "value": value})


def _state(subject_id: UUID, name: str, state: str, state_fips: str) -> CanonicalJurisdictionSubject:
    return CanonicalJurisdictionSubject(
        id=subject_id,
        name=name,
        jurisdiction_kind="state",
        parent_id=None,
        state=state,
        identifiers=(_identifier("state_fips", state_fips),),
    )


def _municipality(
    subject_id: UUID,
    name: str,
    parent_id: UUID,
    state: str,
    place_geoid: str,
) -> CanonicalJurisdictionSubject:
    return CanonicalJurisdictionSubject(
        id=subject_id,
        name=name,
        jurisdiction_kind="municipality",
        parent_id=parent_id,
        state=state,
        identifiers=(_identifier("place_geoid", place_geoid),),
    )


def _county(
    subject_id: UUID,
    name: str,
    parent_id: UUID,
    state: str,
    county_geoid: str,
) -> CanonicalJurisdictionSubject:
    return CanonicalJurisdictionSubject(
        id=subject_id,
        name=name,
        jurisdiction_kind="county",
        parent_id=parent_id,
        state=state,
        identifiers=(_identifier("county_geoid", county_geoid),),
    )


def _consolidated_city_county(
    subject_id: UUID,
    name: str,
    parent_id: UUID,
    state: str,
    place_geoid: str,
    county_geoid: str,
) -> CanonicalJurisdictionSubject:
    return CanonicalJurisdictionSubject(
        id=subject_id,
        name=name,
        jurisdiction_kind="consolidated_city_county",
        parent_id=parent_id,
        state=state,
        identifiers=(
            _identifier("place_geoid", place_geoid),
            _identifier("county_geoid", county_geoid),
        ),
    )


# These are explicit canonical-owner projection specimens for the resolver contract,
# not a stored city registry, runtime-data assertion, or public municipality selection.
_OWNER_SPECIMENS = (
    _state(_CA_ID, "California", "CA", "06"),
    _state(_NY_ID, "New York", "NY", "36"),
    _state(_PA_ID, "Pennsylvania", "PA", "42"),
    _municipality(_LA_ID, "Los Angeles", _CA_ID, "CA", "0644000"),
    _municipality(_NYC_ID, "New York City", _NY_ID, "NY", "3651000"),
    _consolidated_city_county(_PHL_ID, "Philadelphia", _PA_ID, "PA", "4260000", "42101"),
    _consolidated_city_county(_SF_ID, "San Francisco", _CA_ID, "CA", "0667000", "06075"),
)


def _config_identity(city_code: str) -> JurisdictionIdentity:
    return load_jurisdiction_config(_CITIES_ROOT / city_code / "config.yaml").jurisdiction


@pytest.mark.parametrize(
    (
        "city_code",
        "reference",
        "expected_id",
        "expected_kind",
        "expected_place_geoid",
        "expected_county_geoid",
    ),
    (
        pytest.param(
            "LA",
            _identifier("place_geoid", "0644000"),
            _LA_ID,
            "municipality",
            "0644000",
            None,
            id="los_angeles",
        ),
        pytest.param(
            "NYC",
            _identifier("place_geoid", "3651000"),
            _NYC_ID,
            "municipality",
            "3651000",
            None,
            id="new_york_city",
        ),
        pytest.param(
            "PHL",
            _identifier("county_geoid", "42101"),
            _PHL_ID,
            "consolidated_city_county",
            "4260000",
            "42101",
            id="philadelphia_county_reference",
        ),
        pytest.param(
            "PHL",
            _identifier("place_geoid", "4260000"),
            _PHL_ID,
            "consolidated_city_county",
            "4260000",
            "42101",
            id="philadelphia_place_reference",
        ),
        pytest.param(
            "SF",
            _identifier("place_geoid", "0667000"),
            _SF_ID,
            "consolidated_city_county",
            "0667000",
            "06075",
            id="san_francisco_place_reference",
        ),
        pytest.param(
            "SF",
            _identifier("county_geoid", "06075"),
            _SF_ID,
            "consolidated_city_county",
            "0667000",
            "06075",
            id="san_francisco_county_reference",
        ),
    ),
)
def test_municipality_geography_resolver_matrix(
    city_code: str,
    reference: GeographyIdentifier,
    expected_id: UUID,
    expected_kind: str,
    expected_place_geoid: str,
    expected_county_geoid: str | None,
) -> None:
    config_identity = _config_identity(city_code)

    resolved = resolve_municipality_geography(
        config_identity=config_identity,
        reference=reference,
        target_kind=expected_kind,
        canonical_subjects=_OWNER_SPECIMENS,
    )

    assert resolved.config_identity == ("municipality", city_code)
    assert resolved.jurisdiction_id == expected_id
    assert resolved.geographic_kind == expected_kind
    assert resolved.state == config_identity.parent
    assert resolved.place_geoid == expected_place_geoid
    assert resolved.county_geoid == expected_county_geoid
    assert set(resolved.__class__.model_fields) == {
        "config_identity",
        "jurisdiction_id",
        "name",
        "geographic_kind",
        "state",
        "place_geoid",
        "county_geoid",
    }


def test_municipality_geography_refuses_bare_fips() -> None:
    with pytest.raises(ValidationError, match="kind"):
        GeographyIdentifier.model_validate({"namespace": "core.jurisdiction", "kind": "fips", "value": "06037"})

    with pytest.raises(WrongGeographyIdentifierKindError, match="bare FIPS is refused"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference="06037",  # type: ignore[arg-type]
            target_kind="municipality",
            canonical_subjects=_OWNER_SPECIMENS,
        )


def test_municipality_geography_refuses_zero_and_multiple_matches() -> None:
    with pytest.raises(MissingGeographyMatchError, match=r"found 0.*core\.jurisdiction"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0699999"),
            target_kind="municipality",
            canonical_subjects=_OWNER_SPECIMENS,
        )

    duplicate = _municipality(
        UUID("20000000-0000-4000-8000-000000000099"),
        "Duplicate subject",
        _CA_ID,
        "CA",
        "0644000",
    )
    with pytest.raises(AmbiguousGeographyMatchError, match=r"found 2.*core\.jurisdiction"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(*_OWNER_SPECIMENS, duplicate),
        )


@pytest.mark.parametrize("city_code", ("LA", "NYC"), ids=("los_angeles", "new_york_county"))
def test_ordinary_municipality_refuses_explicit_county_equivalent_kind(city_code: str) -> None:
    config_identity = _config_identity(city_code)
    subject_id = _LA_ID if city_code == "LA" else _NYC_ID
    unsafe_county_identifier = _identifier(
        "county_geoid",
        config_identity.fips,
    )
    subjects = tuple(
        subject.model_copy(update={"identifiers": (*subject.identifiers, unsafe_county_identifier)})
        if subject.id == subject_id
        else subject
        for subject in _OWNER_SPECIMENS
    )

    with pytest.raises(WrongGeographyIdentifierKindError, match=r"unexpected identifier kind.*county_geoid"):
        resolve_municipality_geography(
            config_identity=config_identity,
            reference=unsafe_county_identifier,
            target_kind="municipality",
            canonical_subjects=subjects,
        )


def test_municipality_geography_refuses_parent_contradiction_and_state_code_collision() -> None:
    los_angeles = _config_identity("LA").model_copy(update={"parent": "NY"})

    with pytest.raises(GeographyParentContradictionError, match=r"config parent 'NY'.*canonical parent 'CA'"):
        resolve_municipality_geography(
            config_identity=los_angeles,
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=_OWNER_SPECIMENS,
        )

    louisiana = _config_identity("LA").model_copy(update={"type": "state", "parent": None})
    with pytest.raises(GeographySubjectKindError, match=r"config identity state/LA"):
        resolve_municipality_geography(
            config_identity=louisiana,
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=_OWNER_SPECIMENS,
        )


def test_ordinary_municipality_accepts_county_to_state_ancestry() -> None:
    los_angeles_county = _county(_LA_COUNTY_ID, "Los Angeles County", _CA_ID, "CA", "06037")
    los_angeles = _OWNER_SPECIMENS[3].model_copy(update={"parent_id": _LA_COUNTY_ID})

    resolved = resolve_municipality_geography(
        config_identity=_config_identity("LA"),
        reference=_identifier("place_geoid", "0644000"),
        target_kind="municipality",
        canonical_subjects=(*_OWNER_SPECIMENS[:3], los_angeles_county, los_angeles, *_OWNER_SPECIMENS[4:]),
    )

    assert resolved.jurisdiction_id == _LA_ID
    assert resolved.state == "CA"
    assert resolved.place_geoid == "0644000"
    assert resolved.county_geoid is None


@pytest.mark.parametrize(
    "canonical_subjects",
    (
        pytest.param(
            (
                *_OWNER_SPECIMENS[:3],
                _OWNER_SPECIMENS[3].model_copy(update={"parent_id": _LA_ID}),
                *_OWNER_SPECIMENS[4:],
            ),
            id="municipality_self_cycle",
        ),
        pytest.param(
            (
                *_OWNER_SPECIMENS[:3],
                _county(_LA_COUNTY_ID, "Los Angeles County", _LA_ID, "CA", "06037"),
                _OWNER_SPECIMENS[3].model_copy(update={"parent_id": _LA_COUNTY_ID}),
                *_OWNER_SPECIMENS[4:],
            ),
            id="municipality_county_cycle",
        ),
        pytest.param(
            (
                _OWNER_SPECIMENS[0].model_copy(update={"parent_id": _CA_ID}),
                *_OWNER_SPECIMENS[1:],
            ),
            id="state_self_cycle",
        ),
    ),
)
def test_municipality_geography_refuses_ancestry_cycles(
    canonical_subjects: tuple[CanonicalJurisdictionSubject, ...],
) -> None:
    with pytest.raises(GeographyParentContradictionError, match="ancestry cycle"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=canonical_subjects,
        )


@pytest.mark.parametrize(
    ("county_parent_id", "county_state", "county_geoid", "error_match"),
    (
        pytest.param(
            UUID("40000000-0000-4000-8000-000000000001"),
            "CA",
            "06037",
            "must resolve exactly once; found 0",
            id="missing_state_ancestor",
        ),
        pytest.param(
            _CA_ID,
            "NY",
            "06037",
            "county state 'NY' contradicts canonical state 'CA'",
            id="contradictory_state_ancestor",
        ),
        pytest.param(
            _CA_ID,
            "CA",
            "36037",
            r"county_geoid '36037'.*state_fips '06'",
            id="cross_state_county_geoid",
        ),
    ),
)
def test_county_ancestry_requires_one_consistent_state_ancestor(
    county_parent_id: UUID,
    county_state: str,
    county_geoid: str,
    error_match: str,
) -> None:
    los_angeles_county = _county(
        _LA_COUNTY_ID,
        "Los Angeles County",
        county_parent_id,
        county_state,
        county_geoid,
    )
    los_angeles = _OWNER_SPECIMENS[3].model_copy(update={"parent_id": _LA_COUNTY_ID})

    with pytest.raises(GeographyParentContradictionError, match=error_match):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(*_OWNER_SPECIMENS[:3], los_angeles_county, los_angeles, *_OWNER_SPECIMENS[4:]),
        )


def test_direct_state_ancestry_requires_a_terminal_state_root() -> None:
    california_with_missing_parent = _OWNER_SPECIMENS[0].model_copy(
        update={"parent_id": UUID("40000000-0000-4000-8000-000000000002")}
    )

    with pytest.raises(GeographyParentContradictionError, match="state ancestor.*must be terminal"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(california_with_missing_parent, *_OWNER_SPECIMENS[1:]),
        )


@pytest.mark.parametrize(
    ("city_code", "reference", "target_kind"),
    (
        pytest.param(
            "LA",
            _identifier("place_geoid", "0667000"),
            "consolidated_city_county",
            id="los_angeles_cannot_bind_san_francisco",
        ),
        pytest.param(
            "SF",
            _identifier("place_geoid", "0644000"),
            "municipality",
            id="san_francisco_cannot_bind_los_angeles",
        ),
    ),
)
def test_municipality_geography_refuses_wrong_same_state_subject(
    city_code: str,
    reference: GeographyIdentifier,
    target_kind: str,
) -> None:
    with pytest.raises(GeographyIdentityContradictionError, match="municipality name"):
        resolve_municipality_geography(
            config_identity=_config_identity(city_code),
            reference=reference,
            target_kind=target_kind,
            canonical_subjects=_OWNER_SPECIMENS,
        )


def test_municipality_geography_refuses_explicit_target_kind_mismatch() -> None:
    with pytest.raises(GeographySubjectKindError, match="explicit target kind"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="consolidated_city_county",
            canonical_subjects=_OWNER_SPECIMENS,
        )


def test_municipality_geography_refuses_geoid_parent_state_fips_contradictions() -> None:
    california_with_new_york_fips = _OWNER_SPECIMENS[0].model_copy(
        update={"identifiers": (_identifier("state_fips", "36"),)}
    )
    with pytest.raises(GeographyParentContradictionError, match=r"contradicts parent state_fips '36'"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(california_with_new_york_fips, *_OWNER_SPECIMENS[1:]),
        )

    philadelphia_with_cross_state_place = _OWNER_SPECIMENS[5].model_copy(
        update={
            "identifiers": (
                _identifier("place_geoid", "0660000"),
                _identifier("county_geoid", "42101"),
            )
        }
    )
    with pytest.raises(GeographyParentContradictionError, match=r"place_geoid.*state_fips '42'"):
        resolve_municipality_geography(
            config_identity=_config_identity("PHL"),
            reference=_identifier("county_geoid", "42101"),
            target_kind="consolidated_city_county",
            canonical_subjects=(*_OWNER_SPECIMENS[:5], philadelphia_with_cross_state_place, _OWNER_SPECIMENS[6]),
        )


@pytest.mark.parametrize(
    ("city_code", "subject_id", "reference", "target_kind", "extra_identifier"),
    (
        pytest.param(
            "LA",
            _LA_ID,
            _identifier("place_geoid", "0644000"),
            "municipality",
            _identifier("county_geoid", "06037"),
            id="ordinary_subject_extra_county_geoid",
        ),
        pytest.param(
            "LA",
            _LA_ID,
            _identifier("place_geoid", "0644000"),
            "municipality",
            _identifier("state_fips", "06"),
            id="ordinary_subject_extra_state_fips",
        ),
        pytest.param(
            "PHL",
            _PHL_ID,
            _identifier("county_geoid", "42101"),
            "consolidated_city_county",
            _identifier("state_fips", "42"),
            id="consolidated_subject_extra_state_fips",
        ),
    ),
)
def test_municipality_geography_refuses_extra_wrong_kind_identifier_on_matched_subject(
    city_code: str,
    subject_id: UUID,
    reference: GeographyIdentifier,
    target_kind: str,
    extra_identifier: GeographyIdentifier,
) -> None:
    subjects = tuple(
        subject.model_copy(update={"identifiers": (*subject.identifiers, extra_identifier)})
        if subject.id == subject_id
        else subject
        for subject in _OWNER_SPECIMENS
    )

    with pytest.raises(
        WrongGeographyIdentifierKindError,
        match=rf"unexpected identifier kind.*{extra_identifier.kind}",
    ):
        resolve_municipality_geography(
            config_identity=_config_identity(city_code),
            reference=reference,
            target_kind=target_kind,
            canonical_subjects=subjects,
        )


@pytest.mark.parametrize(
    "extra_identifier",
    (
        pytest.param(_identifier("place_geoid", "0699999"), id="place_geoid"),
        pytest.param(_identifier("county_geoid", "06037"), id="county_geoid"),
    ),
)
def test_municipality_geography_refuses_extra_wrong_kind_identifier_on_state_ancestor(
    extra_identifier: GeographyIdentifier,
) -> None:
    california_with_extra_identifier = _OWNER_SPECIMENS[0].model_copy(
        update={"identifiers": (*_OWNER_SPECIMENS[0].identifiers, extra_identifier)}
    )

    with pytest.raises(
        WrongGeographyIdentifierKindError,
        match=rf"state.*unexpected identifier kind.*{extra_identifier.kind}",
    ):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(california_with_extra_identifier, *_OWNER_SPECIMENS[1:]),
        )


@pytest.mark.parametrize(
    "extra_identifier",
    (
        pytest.param(_identifier("place_geoid", "0699999"), id="place_geoid"),
        pytest.param(_identifier("state_fips", "06"), id="state_fips"),
    ),
)
def test_municipality_geography_refuses_extra_wrong_kind_identifier_on_county_ancestor(
    extra_identifier: GeographyIdentifier,
) -> None:
    los_angeles_county = _county(_LA_COUNTY_ID, "Los Angeles County", _CA_ID, "CA", "06037").model_copy(
        update={
            "identifiers": (
                _identifier("county_geoid", "06037"),
                extra_identifier,
            )
        }
    )
    los_angeles = _OWNER_SPECIMENS[3].model_copy(update={"parent_id": _LA_COUNTY_ID})

    with pytest.raises(
        WrongGeographyIdentifierKindError,
        match=rf"county.*unexpected identifier kind.*{extra_identifier.kind}",
    ):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=(*_OWNER_SPECIMENS[:3], los_angeles_county, los_angeles, *_OWNER_SPECIMENS[4:]),
        )


def test_consolidated_city_county_refuses_state_fips_reference_kind() -> None:
    philadelphia_with_extra_state_fips = _OWNER_SPECIMENS[5].model_copy(
        update={"identifiers": (*_OWNER_SPECIMENS[5].identifiers, _identifier("state_fips", "42"))}
    )
    with pytest.raises(WrongGeographyIdentifierKindError, match="cannot resolve from state_fips"):
        resolve_municipality_geography(
            config_identity=_config_identity("PHL"),
            reference=_identifier("state_fips", "42"),
            target_kind="consolidated_city_county",
            canonical_subjects=(*_OWNER_SPECIMENS[:5], philadelphia_with_extra_state_fips, _OWNER_SPECIMENS[6]),
        )


@pytest.mark.parametrize(
    ("city_code", "missing_kind"),
    (
        pytest.param("PHL", "place_geoid", id="philadelphia_place_missing"),
        pytest.param("SF", "county_geoid", id="san_francisco_county_missing"),
    ),
)
def test_consolidated_city_county_requires_both_identifiers_on_one_canonical_subject(
    city_code: str,
    missing_kind: str,
) -> None:
    config_identity = _config_identity(city_code)
    subject_id = _PHL_ID if city_code == "PHL" else _SF_ID
    reference = _identifier("county_geoid", "42101") if city_code == "PHL" else _identifier("place_geoid", "0667000")
    retained_subjects = tuple(
        subject.model_copy(
            update={
                "identifiers": tuple(
                    identifier for identifier in subject.identifiers if identifier.kind != missing_kind
                )
            }
        )
        if subject.id == subject_id
        else subject
        for subject in _OWNER_SPECIMENS
    )
    split_identifier = next(
        identifier
        for subject in _OWNER_SPECIMENS
        if subject.id == subject_id
        for identifier in subject.identifiers
        if identifier.kind == missing_kind
    )
    split_subject = CanonicalJurisdictionSubject(
        id=UUID(f"20000000-0000-4000-8000-0000000000{'13' if city_code == 'PHL' else '14'}"),
        name=f"Split {city_code} subject",
        jurisdiction_kind="county" if missing_kind == "county_geoid" else "municipality",
        parent_id=_PA_ID if city_code == "PHL" else _CA_ID,
        state=config_identity.parent,
        identifiers=(split_identifier,),
    )

    with pytest.raises(ConsolidatedGeographyEvidenceError, match=r"same core\.jurisdiction subject"):
        resolve_municipality_geography(
            config_identity=config_identity,
            reference=reference,
            target_kind="consolidated_city_county",
            canonical_subjects=(*retained_subjects, split_subject),
        )


def test_municipality_geography_refuses_wrong_subject_kind_and_non_state_parent() -> None:
    wrong_kind = _OWNER_SPECIMENS[3].model_copy(update={"jurisdiction_kind": "county"})
    subjects_with_wrong_kind = (*_OWNER_SPECIMENS[:3], wrong_kind, *_OWNER_SPECIMENS[4:])
    with pytest.raises(GeographySubjectKindError, match="found county"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=subjects_with_wrong_kind,
        )

    non_state_parent = _OWNER_SPECIMENS[0].model_copy(update={"jurisdiction_kind": "special_district"})
    subjects_with_non_state_parent = (non_state_parent, *_OWNER_SPECIMENS[1:])
    with pytest.raises(
        GeographyParentContradictionError,
        match=r"ancestry must reach a state.*special_district",
    ):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=subjects_with_non_state_parent,
        )


def test_municipality_geography_refuses_duplicate_owner_subject_rows() -> None:
    duplicate_subjects: Iterable[CanonicalJurisdictionSubject] = (
        *_OWNER_SPECIMENS,
        _OWNER_SPECIMENS[0].model_copy(update={"identifiers": (_identifier("state_fips", "99"),)}),
    )

    with pytest.raises(AmbiguousGeographyMatchError, match=r"duplicate core\.jurisdiction subject id"):
        resolve_municipality_geography(
            config_identity=_config_identity("LA"),
            reference=_identifier("place_geoid", "0644000"),
            target_kind="municipality",
            canonical_subjects=duplicate_subjects,
        )


@pytest.mark.parametrize(
    ("county_name", "county_geoid"),
    (
        pytest.param("Bronx County", "36005", id="bronx"),
        pytest.param("Kings County", "36047", id="kings"),
        pytest.param("New York County", "36061", id="new_york"),
        pytest.param("Queens County", "36081", id="queens"),
        pytest.param("Richmond County", "36085", id="richmond"),
    ),
)
def test_new_york_city_refuses_every_constituent_county_as_the_municipality(
    county_name: str,
    county_geoid: str,
) -> None:
    county = _county(
        UUID(f"30000000-0000-4000-8000-000000000{county_geoid[-3:]}"),
        county_name,
        _NY_ID,
        "NY",
        county_geoid,
    )

    with pytest.raises(GeographySubjectKindError, match="explicit target kind municipality; found county"):
        resolve_municipality_geography(
            config_identity=_config_identity("NYC"),
            reference=_identifier("county_geoid", county_geoid),
            target_kind="municipality",
            canonical_subjects=(*_OWNER_SPECIMENS, county),
        )


def test_sql_projection_is_parameterized_bounded_and_excludes_legacy_fips() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    reference = _identifier("place_geoid", "0644000")

    assert project_canonical_jurisdiction_subjects(conn, reference=reference) == ()

    sql, params = cursor.execute.call_args.args
    compact_sql = " ".join(sql.lower().split())
    assert "with target as" in compact_sql
    assert compact_sql.count("join target") == 2
    assert "limit" not in compact_sql
    assert re.search(r"\bfips\b", compact_sql) is None
    assert params == {"kind": "place_geoid", "value": "0644000"}


def test_sql_projection_rejects_state_fips_before_database_access() -> None:
    conn = MagicMock()

    with pytest.raises(WrongGeographyIdentifierKindError, match="cannot project from state_fips"):
        project_canonical_jurisdiction_subjects(
            conn,
            reference=_identifier("state_fips", "06"),
        )

    conn.cursor.assert_not_called()


def _seed_sql_projection_fixture(db_conn: psycopg.Connection) -> None:
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "core"
        / "schema"
        / "migrations"
        / "2026_08_27_typed_jurisdiction_identity.sql"
    )
    db_conn.execute(migration_path.read_text(encoding="utf-8"))
    db_conn.execute(
        """
        INSERT INTO core.jurisdiction (
            id,
            name,
            jurisdiction_type,
            fips,
            state_fips,
            county_geoid,
            place_geoid,
            parent_id,
            state
        )
        VALUES
            (%s, 'California', 'state', '06', '06', NULL, NULL, NULL, 'CA'),
            (%s, 'Los Angeles County', 'county', '06037', NULL, '06037', NULL, %s, 'CA'),
            (%s, 'Los Angeles', 'municipality', '06440', NULL, NULL, '0644000', %s, 'CA'),
            (%s, 'San Francisco', 'municipality', '06075', NULL, '06075', '0667000', %s, 'CA'),
            (%s, 'New York City', 'municipality', '36061', NULL, NULL, NULL, NULL, 'NY')
        """,
        (
            _CA_ID,
            _LA_COUNTY_ID,
            _CA_ID,
            _LA_ID,
            _LA_COUNTY_ID,
            _SF_ID,
            _CA_ID,
            _NYC_ID,
        ),
    )


@pytest.mark.integration
def test_sql_projection_ordinary_municipality_ignores_legacy_fips(
    db_conn: psycopg.Connection,
) -> None:
    _seed_sql_projection_fixture(db_conn)

    subjects = project_canonical_jurisdiction_subjects(
        db_conn,
        reference=_identifier("place_geoid", "0644000"),
    )
    subject_by_id = {subject.id: subject for subject in subjects}

    assert set(subject_by_id) == {_CA_ID, _LA_COUNTY_ID, _LA_ID}
    assert subject_by_id[_LA_ID].jurisdiction_kind == "municipality"
    assert subject_by_id[_LA_ID].identifiers == (_identifier("place_geoid", "0644000"),)
    assert subject_by_id[_LA_COUNTY_ID].identifiers == (_identifier("county_geoid", "06037"),)
    assert set(subject_by_id[_LA_ID].model_fields) == {
        "id",
        "name",
        "jurisdiction_kind",
        "parent_id",
        "state",
        "identifiers",
    }
    resolved = resolve_municipality_geography(
        config_identity=_config_identity("LA"),
        reference=_identifier("place_geoid", "0644000"),
        target_kind="municipality",
        canonical_subjects=subjects,
    )
    assert resolved.place_geoid == "0644000"
    assert resolved.county_geoid is None
    assert db_conn.execute("SELECT fips FROM core.jurisdiction WHERE id = %s", (_LA_ID,)).fetchone()[0] == "06440"


@pytest.mark.integration
def test_sql_projection_derives_consolidated_city_county_from_same_subject(
    db_conn: psycopg.Connection,
) -> None:
    _seed_sql_projection_fixture(db_conn)

    subjects = project_canonical_jurisdiction_subjects(
        db_conn,
        reference=_identifier("county_geoid", "06075"),
    )
    subject_by_id = {subject.id: subject for subject in subjects}

    assert set(subject_by_id) == {_CA_ID, _SF_ID}
    assert subject_by_id[_SF_ID].jurisdiction_kind == "consolidated_city_county"
    assert subject_by_id[_SF_ID].identifiers == (
        _identifier("county_geoid", "06075"),
        _identifier("place_geoid", "0667000"),
    )
    resolved = resolve_municipality_geography(
        config_identity=_config_identity("SF"),
        reference=_identifier("county_geoid", "06075"),
        target_kind="consolidated_city_county",
        canonical_subjects=subjects,
    )
    assert resolved.place_geoid == "0667000"
    assert resolved.county_geoid == "06075"
    raw_type = db_conn.execute(
        "SELECT jurisdiction_type FROM core.jurisdiction WHERE id = %s",
        (_SF_ID,),
    ).fetchone()[0]
    assert raw_type == "municipality"


@pytest.mark.integration
def test_sql_projection_leaves_five_digit_municipality_untyped(
    db_conn: psycopg.Connection,
) -> None:
    _seed_sql_projection_fixture(db_conn)

    reference = _identifier("place_geoid", "3651000")
    subjects = project_canonical_jurisdiction_subjects(db_conn, reference=reference)

    assert subjects == ()
    with pytest.raises(MissingGeographyMatchError):
        resolve_municipality_geography(
            config_identity=_config_identity("NYC"),
            reference=reference,
            target_kind="municipality",
            canonical_subjects=subjects,
        )
    assert db_conn.execute(
        "SELECT fips, place_geoid FROM core.jurisdiction WHERE id = %s",
        (_NYC_ID,),
    ).fetchone() == ("36061", None)
