from __future__ import annotations

from datetime import date

import pytest

from api.models.regional_navigation import (
    RegionalAuthorityContext,
    RegionalFinanceState,
    RegionalNavigationNode,
    RegionalSubjectIdentity,
)
from api.queries.regional_navigation import (
    _REGIONAL_CANDIDATE_SQL,
    _REGIONAL_SOURCE_RUNTIME_SQL,
    resolve_regional_navigation_node,
)


@pytest.mark.parametrize(
    ("kind", "code", "slug", "path"),
    [
        ("state", "WA", None, "/state/WA"),
        ("county", "NC_WAKE", "wake", "/state/NC/county/wake"),
        ("municipality", "WA_SEATTLE", "seattle", "/state/WA/municipality/seattle"),
        (
            "school_district",
            "SYNTH_SCHOOL",
            "synthetic-school",
            "/state/WA/school-district/synthetic-school",
        ),
        (
            "special_district",
            "SYNTH_SPECIAL",
            "synthetic-special",
            "/state/WA/special-district/synthetic-special",
        ),
    ],
)
def test_every_regional_subject_kind_serializes_without_inventing_finance(
    kind: str,
    code: str,
    slug: str | None,
    path: str,
) -> None:
    subject = RegionalSubjectIdentity(kind=kind, code=code, name=code)
    context = RegionalAuthorityContext(
        subject=subject,
        public_route=None,
        acquisition_scope=None,
        provenance_scope=None,
        relation="unresolved",
        filing_authorities=[],
        included_scopes=[],
        excluded_scopes=[],
        provenance_scopes=[],
        aggregation_disposition="refuse",
        evidence_date=None,
        translation_status="refused",
        refusal_reasons=["No exact typed authority translation was supplied."],
    )

    node = RegionalNavigationNode(
        kind=kind,
        name=code,
        state_code="WA" if kind != "county" else "NC",
        state_name="Washington" if kind != "county" else "North Carolina",
        slug=slug,
        canonical_path=path,
        geometry_reference=None,
        finance=RegionalFinanceState(
            status="unavailable",
            authority_context=context,
            authority_health=[],
            reason="Finance refuses without typed authority proof.",
        ),
        finance_detail=None,
        proxy_analysis=None,
    )

    assert node.finance.authority_context.subject.kind == kind
    assert node.finance.authority_context.translation_status == "refused"
    assert node.finance_detail is None


def test_real_route_controls_project_typed_authority_context_without_flattening_overlap() -> None:
    washington = resolve_regional_navigation_node(kind="state", state_code="WA", slug=None)
    new_york = resolve_regional_navigation_node(kind="state", state_code="NY", slug=None)
    seattle = resolve_regional_navigation_node(kind="municipality", state_code="WA", slug="seattle")
    new_york_city = resolve_regional_navigation_node(
        kind="municipality",
        state_code="NY",
        slug="new-york-city",
    )
    wake = resolve_regional_navigation_node(kind="county", state_code="NC", slug="wake")

    assert washington is not None
    assert washington.finance.authority_context.subject == RegionalSubjectIdentity(
        kind="state",
        code="WA",
        name="Washington",
    )
    assert washington.finance.authority_context.acquisition_scope == "state/WA"
    assert washington.finance.authority_context.public_route == "/state/WA"

    assert new_york is not None
    assert new_york.finance.authority_context.subject == RegionalSubjectIdentity(
        kind="state",
        code="NY",
        name="New York",
    )
    assert new_york.finance.authority_context.translation_status == "refused"
    assert new_york.finance_detail is None

    assert seattle is not None
    assert seattle.finance.authority_context.relation == "partitioned_overlapping"
    assert [authority.code for authority in seattle.finance.authority_context.filing_authorities] == [
        "WA",
        "WA_SEATTLE_CITY_CLERK",
        "WA_SEEC",
    ]
    assert seattle.finance.authority_context.aggregation_disposition == "refuse_combination"
    assert seattle.finance.authority_context.evidence_date == date(2026, 8, 28)

    assert new_york_city is not None
    assert new_york_city.finance.authority_context.relation == "partitioned_overlapping"
    assert [authority.code for authority in new_york_city.finance.authority_context.filing_authorities] == [
        "NY",
        "NY_NEW_YORK",
    ]
    assert new_york_city.finance.authority_context.aggregation_disposition == "refuse_combination"

    assert wake is not None
    assert wake.finance.authority_context.subject.kind == "county"
    assert wake.finance.authority_context.translation_status == "refused"
    assert wake.finance.authority_context.filing_authorities == []


def test_shared_regional_sql_has_no_washington_source_inventory_or_storage_identifier() -> None:
    assert "WA PDC" not in _REGIONAL_SOURCE_RUNTIME_SQL
    assert "state/WA" not in _REGIONAL_SOURCE_RUNTIME_SQL
    assert "wa_filer_id" not in _REGIONAL_CANDIDATE_SQL
    assert "office.state = 'WA'" not in _REGIONAL_CANDIDATE_SQL


def test_candidate_contract_exposes_typed_native_identifier_not_washington_storage_key() -> None:
    from api.models.regional_navigation import RegionalCandidate

    assert "native_filer_identifier" in RegionalCandidate.model_fields
    assert "wa_filer_id" not in RegionalCandidate.model_fields
