from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.queries.regional_navigation as regional_navigation_queries
from api.deps import get_db
from api.models.regional_navigation import (
    RegionalFinanceState,
    RegionalFinanceSource,
    RegionalNavigationNode,
    RegionalProxyAnalysis,
)
from api.queries.regional_navigation import (
    list_regional_navigation_children,
    resolve_regional_navigation_node,
    search_regional_navigation_nodes,
)
from api.routes.regional_navigation import router
from domains.campaign_finance.coverage.lifecycle import AuthorityPromotionReceipt
from domains.campaign_finance.coverage.registry import load_registry
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config


def _client(conn: object | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: conn
    return TestClient(app)


def _promotion_receipt(source_identities: list[str], observed_at: datetime) -> AuthorityPromotionReceipt:
    return AuthorityPromotionReceipt.model_validate(
        {
            "schema_version": 1,
            "issued_at": observed_at.isoformat(),
            "jurisdiction_code": "WA",
            "geographic_subject": {"kind": "state", "code": "WA"},
            "filing_authority": {"kind": "state", "code": "WA"},
            "authority_relation": "independent",
            "aggregation_disposition": "not_applicable",
            "provenance_scope": "state/WA",
            "promotion_evidence": {
                "authority_identity": "state/WA",
                "authority_relation": "independent",
                "aggregation_disposition": "not_applicable",
                "expected_source_identities": source_identities,
                "source_evidence": [
                    {
                        "source_identity": source_identity,
                        "freshness_status": "fresh",
                        "observed_at": observed_at.isoformat(),
                    }
                    for source_identity in source_identities
                ],
                "recurrence_evidence": [
                    {
                        "source_identity": source_identity,
                        "pull_status": "success",
                        "execution_origin": "scheduled",
                        "completed_at": observed_at.isoformat(),
                    }
                    for source_identity in source_identities
                ],
                "provenance_source_identities": source_identities,
                "keel_source_identities": source_identities,
                "deployed_source_identities": source_identities,
                "source_revision": "a" * 40,
                "api_revision": "a" * 40,
                "web_revision": "a" * 40,
            },
            "canonical_evidence": [
                {"kind": kind, "path": f"/{kind}.json", "sha256": "a" * 64}
                for kind in (
                    "canary_ledger",
                    "scheduled_recurrence",
                    "filing_authority",
                    "provenance",
                    "keel",
                    "serving_deploy",
                    "surface_parity",
                )
            ],
        }
    )


def test_washington_resolution_keeps_known_authority_but_refuses_a_guessed_zero_without_db() -> None:
    node = resolve_regional_navigation_node(kind="state", state_code="WA", slug=None)

    assert node is not None
    assert node.canonical_path == "/state/WA"
    assert node.finance.status == "unavailable"
    context = node.finance.authority_context
    assert context.subject.model_dump() == {"kind": "state", "code": "WA", "name": "Washington"}
    assert context.public_route == "/state/WA"
    assert context.acquisition_scope == "state/WA"
    assert context.provenance_scope is None
    assert context.relation == "unresolved"
    assert context.translation_status == "refused"
    assert context.aggregation_disposition == "refuse"
    assert node.finance_detail is not None
    assert {row.status for row in node.finance_detail.money} == {"unavailable"}
    assert all(row.amount is None for row in node.finance_detail.money)
    assert "A database-backed authority projection was not requested." in node.finance_detail.named_gaps
    assert node.finance_detail.authority_health[0].promotion_eligible is False


def test_regional_api_uses_exact_promotion_receipt_for_authority_and_health_without_combining_geographies() -> None:
    observed_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    config = load_jurisdiction_config(regional_navigation_queries._WA_CONFIG_PATH)
    plan = regional_navigation_queries._build_query_plan(config)
    source_identities = [f"{plan.operational_scope}:{source.name}" for _, _, source in plan.source_order]
    receipt = _promotion_receipt(source_identities, observed_at)
    registry = load_registry(regional_navigation_queries.DEFAULT_REGISTRY_PATH)
    context = regional_navigation_queries._authority_context(
        subject=plan.subject,
        canonical_path="/state/WA",
        registry=registry,
        official_urls={plan.authority_code: plan.source_order[0][2].url},
        promotion_receipt=receipt,
    )
    sources = [
        RegionalFinanceSource(
            class_key=class_key,
            authority_code=plan.authority_code,
            source_identity=f"{plan.operational_scope}:{source.name}",
            name=source.name,
            url=source.url,
            status="available",
            last_successful_pull=observed_at,
            last_verified_working=source.last_verified_working,
            latest_refresh_completed_at=observed_at,
            latest_refresh_status="success",
            latest_refresh_execution_origin="scheduled",
            recurrence_status="qualified",
            reason="Exact source is current.",
        )
        for class_key, _, source in plan.source_order
    ]

    health = regional_navigation_queries._health_for_sources(
        plan=plan,
        context=context,
        sources=sources,
        promotion_receipt=receipt,
    )

    assert context.subject.model_dump() == {"kind": "state", "code": "WA", "name": "Washington"}
    assert context.relation == "independent"
    assert context.translation_status == "resolved"
    assert context.provenance_scope == "state/WA"
    assert context.aggregation_disposition == "not_applicable"
    assert [authority.code for authority in context.filing_authorities] == ["WA"]
    assert health[0].promotion_eligible is True
    assert health[0].revision_parity == "match"
    assert health[0].deployed_revision == "a" * 40
    assert health[0].refusal_reasons == []

    seattle = resolve_regional_navigation_node(kind="municipality", state_code="WA", slug="seattle")
    assert seattle is not None
    assert seattle.finance.authority_context.aggregation_disposition == "refuse_combination"


def test_regional_api_loads_the_shared_promotion_receipt_environment_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    config = load_jurisdiction_config(regional_navigation_queries._WA_CONFIG_PATH)
    plan = regional_navigation_queries._build_query_plan(config)
    source_identities = [f"{plan.operational_scope}:{source.name}" for _, _, source in plan.source_order]
    receipt = _promotion_receipt(source_identities, observed_at)
    receipt_path = "/absolute/evidence/authority-promotion-receipt.json"
    monkeypatch.setenv("CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON", receipt_path)
    observed_paths: list[str] = []

    def load_receipt(path: str) -> AuthorityPromotionReceipt:
        observed_paths.append(path)
        return receipt

    monkeypatch.setattr(regional_navigation_queries, "load_authority_promotion_receipt", load_receipt)

    _, context, _, _, _, loaded_receipt = regional_navigation_queries._load_owner_context()

    assert observed_paths == [receipt_path]
    assert loaded_receipt == receipt
    assert context.relation == "independent"
    assert context.translation_status == "resolved"


def test_non_selected_state_keeps_geography_without_state_finance_detail() -> None:
    north_carolina = resolve_regional_navigation_node(kind="state", state_code="NC", slug=None)

    assert north_carolina is not None
    assert north_carolina.finance_detail is None
    assert north_carolina.finance.status == "unavailable"
    assert north_carolina.finance.authority_context.subject.code == "NC"
    assert north_carolina.finance.authority_context.translation_status == "refused"


def test_wake_is_an_explicit_committee_city_proxy_not_county_coverage() -> None:
    node = resolve_regional_navigation_node(kind="county", state_code="NC", slug="wake")

    assert node is not None
    assert node.geometry_reference is not None
    assert node.geometry_reference.value == "nc_county_wake"
    assert node.finance.status == "unavailable"
    assert node.finance.authority_context.subject.code == "NC_WAKE"
    assert node.finance.authority_context.relation == "unresolved"
    assert node.finance.authority_context.aggregation_disposition == "refuse"
    assert node.proxy_analysis is not None
    assert node.proxy_analysis.model_dump() == {
        "label": "Mapped committee-city disbursements",
        "scope_label": "Raleigh and Wake Forest committees",
        "excludes": ["county-wide finance", "donor residence", "candidate residence"],
        "overlap_disposition": "not_combined",
    }


def test_seattle_keeps_parent_route_compatibility_without_flattening_typed_overlap() -> None:
    node = resolve_regional_navigation_node(kind="municipality", state_code="WA", slug="seattle")

    assert node is not None
    assert node.finance.status == "unavailable"
    context = node.finance.authority_context
    assert context.subject.code == "WA_SEATTLE"
    assert context.relation == "partitioned_overlapping"
    assert [authority.code for authority in context.filing_authorities] == [
        "WA",
        "WA_SEATTLE_CITY_CLERK",
        "WA_SEEC",
    ]
    assert context.aggregation_disposition == "refuse_combination"
    assert node.finance_detail is None
    assert "partitioned across PDC, the Seattle City Clerk, and SEEC" in node.finance.reason
    assert "substituted or combined" in node.finance.reason


def test_new_york_city_keeps_direct_route_compatibility_without_flattening_typed_overlap() -> None:
    node = resolve_regional_navigation_node(
        kind="municipality",
        state_code="NY",
        slug="new-york-city",
    )

    assert node is not None
    context = node.finance.authority_context
    assert context.subject.code == "NY_NEW_YORK"
    assert context.relation == "partitioned_overlapping"
    assert [authority.code for authority in context.filing_authorities] == ["NY", "NY_NEW_YORK"]
    assert context.aggregation_disposition == "refuse_combination"
    assert node.finance_detail is None
    assert "bounded post-2020 partition/overlap" in node.finance.reason
    assert "No New York State or combined total" in node.finance.reason


def test_navigation_contract_rejects_cross_jurisdiction_washington_detail() -> None:
    washington = resolve_regional_navigation_node(kind="state", state_code="WA", slug=None)

    assert washington is not None
    payload = washington.model_dump(mode="json")
    with pytest.raises(ValidationError):
        RegionalNavigationNode.model_validate(
            {
                **payload,
                "name": "North Carolina",
                "state_code": "NC",
                "state_name": "North Carolina",
                "canonical_path": "/state/NC",
            }
        )
    with pytest.raises(ValidationError):
        RegionalNavigationNode.model_validate(
            {
                **payload,
                "finance_detail": {**payload["finance_detail"], "authority_health": []},
            }
        )


def test_washington_owner_failure_names_the_contradiction_and_refuses_money(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _UnusedConnection:
        pass

    monkeypatch.setattr(
        regional_navigation_queries,
        "load_jurisdiction_config",
        lambda _path: (_ for _ in ()).throw(ValueError("owner unavailable")),
    )
    node = regional_navigation_queries._state_node("WA", _UnusedConnection())  # type: ignore[arg-type]

    assert node.finance_detail is None
    assert node.finance.status == "unavailable"
    assert node.finance.authority_context.translation_status == "refused"
    assert node.finance.reason == "Checked-in authority owners are contradictory: owner unavailable"


def test_unknown_routes_fail_closed_without_guessing() -> None:
    assert resolve_regional_navigation_node(kind="county", state_code="NC", slug="durham") is None
    assert (
        resolve_regional_navigation_node(
            kind="municipality",
            state_code="CA",
            slug="san-francisco",
        )
        is None
    )
    assert resolve_regional_navigation_node(kind="state", state_code="WA", slug="washington") is None


def test_contract_rejects_untyped_authority_and_claimed_overlap_proof() -> None:
    with pytest.raises(ValidationError):
        RegionalFinanceState.model_validate({"status": "available", "authority": "state-wa", "reason": "unsupported"})
    with pytest.raises(ValidationError):
        RegionalProxyAnalysis.model_validate(
            {
                "label": "unsafe",
                "scope_label": "unsafe",
                "excludes": [],
                "overlap_disposition": "proven_disjoint",
            }
        )


def test_children_expose_only_explicit_route_owned_nodes() -> None:
    assert [node.canonical_path for node in list_regional_navigation_children(state_code="NC", kind="county")] == [
        "/state/NC/county/wake"
    ]
    assert list_regional_navigation_children(state_code="WA", kind="county") == []
    assert [
        node.canonical_path for node in list_regional_navigation_children(state_code="WA", kind="municipality")
    ] == ["/state/WA/municipality/seattle"]
    assert list_regional_navigation_children(state_code="CA", kind="municipality") == []


def test_search_finds_exact_state_county_and_selected_municipality_routes() -> None:
    washington_paths = [node.canonical_path for node in search_regional_navigation_nodes(query="Washington", limit=20)]
    assert washington_paths[0] == "/state/WA"
    assert washington_paths == ["/state/WA", "/state/WA/municipality/seattle"]
    assert [node.canonical_path for node in search_regional_navigation_nodes(query="wake", limit=20)] == [
        "/state/NC/county/wake"
    ]
    assert [node.canonical_path for node in search_regional_navigation_nodes(query="Seattle", limit=20)] == [
        "/state/WA/municipality/seattle"
    ]
    assert search_regional_navigation_nodes(query="San Francisco", limit=20) == []


def test_search_disambiguates_la_without_collapsing_typed_identity() -> None:
    nodes = search_regional_navigation_nodes(query="LA", limit=20)

    assert nodes[0].canonical_path == "/state/LA"
    assert nodes[0].name == "Louisiana"
    assert all(node.canonical_path != "/municipality/LA" for node in nodes)


def test_search_refuses_queries_that_normalize_below_two_characters() -> None:
    assert search_regional_navigation_nodes(query="  ", limit=20) == []
    assert search_regional_navigation_nodes(query=" a ", limit=20) == []

    with _client() as client:
        whitespace_response = client.get("/v1/regional-navigation/search", params={"q": "  "})
        one_character_response = client.get("/v1/regional-navigation/search", params={"q": " a "})

    assert whitespace_response.status_code == 422
    assert one_character_response.status_code == 422


def test_resolve_route_returns_exact_node_and_404s_unselected_municipality() -> None:
    with _client() as client:
        wa_response = client.get(
            "/v1/regional-navigation/resolve",
            params={"kind": "state", "state_code": "WA"},
        )
        sf_response = client.get(
            "/v1/regional-navigation/resolve",
            params={"kind": "municipality", "state_code": "CA", "slug": "san-francisco"},
        )

    assert wa_response.status_code == 200
    assert wa_response.json()["canonical_path"] == "/state/WA"
    assert wa_response.json()["finance"]["status"] == "unavailable"
    assert wa_response.json()["finance_detail"]["money"][0]["amount"] is None
    assert sf_response.status_code == 404


def test_resolve_route_rejects_noncanonical_inputs_before_resolution() -> None:
    with _client() as client:
        lowercase_state = client.get(
            "/v1/regional-navigation/resolve",
            params={"kind": "state", "state_code": "wa"},
        )
        malformed_slug = client.get(
            "/v1/regional-navigation/resolve",
            params={"kind": "county", "state_code": "NC", "slug": "Wake_County"},
        )

    assert lowercase_state.status_code == 422
    assert malformed_slug.status_code == 422


def test_search_and_children_routes_disclose_bounded_route_coverage() -> None:
    with _client() as client:
        search_response = client.get("/v1/regional-navigation/search", params={"q": "wake"})
        children_response = client.get(
            "/v1/regional-navigation/children",
            params={"state_code": "NC", "kind": "county"},
        )

    assert search_response.status_code == 200
    assert search_response.json()["items"][0]["canonical_path"] == "/state/NC/county/wake"
    assert search_response.json()["incomplete_node_kinds"] == [
        "county",
        "municipality",
        "school_district",
        "special_district",
    ]
    assert search_response.json()["has_unsafe_omissions"] is True
    assert children_response.status_code == 200
    assert [item["canonical_path"] for item in children_response.json()["items"]] == ["/state/NC/county/wake"]
