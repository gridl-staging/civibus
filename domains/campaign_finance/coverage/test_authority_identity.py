from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    coverage_authority_linkage_errors,
    load_registry,
    write_registry,
)


def _row_payload(
    *,
    code: str,
    geographic_kind: str,
    relation: dict[str, object],
    name: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "jurisdiction_code": code,
        "name": name or code,
        "jurisdiction_type": geographic_kind,
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-08-28",
        "covers_sub_jurisdictions": False,
        "source_count": 1,
        "source_names": ["Synthetic contract fixture"],
        "runner_wired": False,
        "tier": None,
        "evidence_summary": "Synthetic contract fixture; no public claim.",
        "operational_reason": None,
        "next_action": None,
        "evidence_date": "2026-08-28",
        "authority_relation": relation,
    }
    if geographic_kind == "municipality":
        if relation["relation"] == "inherited":
            payload["parent_jurisdiction_code"] = relation["authority"]["code"]
            payload["municipal_audit_decision"] = "covered_by_parent"
        else:
            payload["parent_jurisdiction_code"] = "SYNTH_PARENT"
            payload["municipal_audit_decision"] = "independent_target"
    return payload


def _authority(kind: str, code: str, *, name: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"kind": kind, "code": code}
    if name is not None:
        payload["name"] = name
    return payload


def _independent(kind: str, code: str, *, name: str | None = None) -> dict[str, object]:
    return {"relation": "independent", "authority": _authority(kind, code, name=name)}


def _inherited(kind: str, code: str) -> dict[str, object]:
    return {"relation": "inherited", "authority": _authority(kind, code)}


def _overlap_relation() -> dict[str, object]:
    state = _authority("state", "SYNTH_STATE")
    county = _authority("county", "SYNTH_COUNTY")
    return {
        "relation": "partitioned_overlapping",
        "authorities": [state, county],
        "precedence": [
            {"authority": county, "scope": "county-only offices"},
            {"authority": state, "scope": "state and statewide-system offices"},
        ],
        "partitions": [
            {"authority": county, "scope": "county-only offices"},
            {"authority": state, "scope": "state and statewide-system offices"},
        ],
        "provenance": [
            {"authority": county, "source_scope": "synthetic-county-source"},
            {"authority": state, "source_scope": "synthetic-state-source"},
        ],
        "deduplication": {
            "disposition": "deduplicate",
            "identity_keys": ["native_filing_id", "transaction_id"],
        },
        "refusals": ["Any class outside the two proved synthetic partitions."],
        "evidence": {
            "owner": "synthetic-test-fixture",
            "receipt": "synthetic/partitioned-overlap.json",
            "receipt_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "packet_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        },
    }


@pytest.mark.parametrize(
    ("authority_kind", "geographic_kind", "authority_name"),
    (
        ("federal", "federal", None),
        ("state", "state", None),
        ("county", "county", None),
        ("municipality", "municipality", None),
        ("school_district", "school_district", None),
        ("special_district", "special_district", None),
        ("named_other", "special_district", "Synthetic Ethics Board"),
    ),
)
def test_independent_relation_supports_every_filing_authority_kind(
    authority_kind: str,
    geographic_kind: str,
    authority_name: str | None,
) -> None:
    row = CoverageRegistryRow.model_validate(
        _row_payload(
            code=f"SYNTH_{authority_kind.upper()}",
            geographic_kind=geographic_kind,
            relation=_independent(
                authority_kind,
                f"SYNTH_{authority_kind.upper()}",
                name=authority_name,
            ),
        )
    )

    assert row.authority_relation.relation == "independent"
    assert row.authority_relation.authority.kind == authority_kind
    assert row.authority_relation.authority.name == authority_name


def test_named_other_authority_requires_an_explicit_name() -> None:
    payload = _row_payload(
        code="SYNTH_OTHER",
        geographic_kind="special_district",
        relation=_independent("named_other", "SYNTH_OTHER"),
    )

    with pytest.raises(ValidationError, match="named_other.*name"):
        CoverageRegistryRow.model_validate(payload)


def test_independent_geographic_authority_must_match_its_registry_row() -> None:
    payload = _row_payload(
        code="SYNTH_STATE",
        geographic_kind="state",
        relation=_independent("state", "DIFFERENT_STATE"),
    )

    with pytest.raises(ValidationError, match="independent geographic authority.*registry row"):
        CoverageRegistryRow.model_validate(payload)


def test_inherited_independent_overlap_and_unresolved_are_distinct_states() -> None:
    inherited = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_CITY",
            geographic_kind="municipality",
            relation=_inherited("state", "SYNTH_STATE"),
        )
    )
    independent = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_INDEPENDENT_CITY",
            geographic_kind="municipality",
            relation=_independent("municipality", "SYNTH_INDEPENDENT_CITY"),
        )
    )
    overlap = CoverageRegistryRow.model_validate(
        _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=_overlap_relation())
    )
    unresolved = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_SCHOOL",
            geographic_kind="school_district",
            relation={
                "relation": "unresolved",
                "candidate_authorities": [_authority("state", "SYNTH_STATE")],
                "reason": "The filing authority has not been established.",
                "aggregation_disposition": "refuse",
            },
        )
    )

    assert inherited.authority_relation.relation == "inherited"
    assert independent.authority_relation.relation == "independent"
    assert overlap.authority_relation.relation == "partitioned_overlapping"
    assert unresolved.authority_relation.relation == "unresolved"
    assert unresolved.authority_relation.aggregation_disposition == "refuse"


@pytest.mark.parametrize(
    "missing_field",
    ("precedence", "partitions", "provenance", "deduplication"),
)
def test_overlap_refuses_when_required_policy_is_missing(missing_field: str) -> None:
    relation = _overlap_relation()
    relation.pop(missing_field)
    payload = _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation)

    with pytest.raises(ValidationError, match=missing_field):
        CoverageRegistryRow.model_validate(payload)


def test_overlap_refuses_incomplete_authority_membership() -> None:
    relation = _overlap_relation()
    relation["provenance"] = [relation["provenance"][0], relation["provenance"][0]]
    payload = _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation)

    with pytest.raises(ValidationError, match="provenance.*exactly once"):
        CoverageRegistryRow.model_validate(payload)


def test_overlap_refusal_disposition_cannot_carry_deduplication_keys() -> None:
    relation = _overlap_relation()
    relation["deduplication"] = {
        "disposition": "refuse_combination",
        "identity_keys": ["must_not_be_used"],
    }
    payload = _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation)

    with pytest.raises(ValidationError, match="refuse_combination.*identity_keys"):
        CoverageRegistryRow.model_validate(payload)


def test_overlap_aggregate_receipt_requires_path_and_hash_together() -> None:
    relation = _overlap_relation()
    relation["evidence"]["aggregate_receipt"] = "receipts/synthetic-aggregate.json"
    payload = _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation)

    with pytest.raises(ValidationError, match="aggregate receipt path and SHA-256"):
        CoverageRegistryRow.model_validate(payload)


def test_cross_row_linkage_requires_inherited_and_overlap_authorities_to_resolve() -> None:
    state = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_STATE",
            geographic_kind="state",
            relation=_independent("state", "SYNTH_STATE"),
        )
    )
    inherited = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_CITY",
            geographic_kind="municipality",
            relation=_inherited("state", "SYNTH_STATE"),
        )
    )
    overlap = CoverageRegistryRow.model_validate(
        _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=_overlap_relation())
    )
    county = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_COUNTY",
            geographic_kind="county",
            relation=_independent("county", "SYNTH_COUNTY"),
        )
    )

    assert (
        coverage_authority_linkage_errors(
            inherited,
            {"SYNTH_STATE": state, "SYNTH_CITY": inherited},
        )
        == []
    )
    assert (
        coverage_authority_linkage_errors(
            overlap,
            {"SYNTH_STATE": state, "SYNTH_COUNTY": county},
        )
        == []
    )
    assert "does not resolve" in " ".join(coverage_authority_linkage_errors(overlap, {"SYNTH_STATE": state}))


def test_named_other_overlap_authority_is_validated_by_explicit_name_and_receipt() -> None:
    relation = _overlap_relation()
    named_other = _authority(
        "named_other",
        "SYNTH_LOCAL_BOARD",
        name="Synthetic Local Filing Board",
    )
    relation["authorities"][1] = named_other
    relation["precedence"][0]["authority"] = named_other
    relation["partitions"][0]["authority"] = named_other
    relation["provenance"][0]["authority"] = named_other
    row = CoverageRegistryRow.model_validate(
        _row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation)
    )
    state = CoverageRegistryRow.model_validate(
        _row_payload(
            code="SYNTH_STATE",
            geographic_kind="state",
            relation=_independent("state", "SYNTH_STATE"),
        )
    )

    assert coverage_authority_linkage_errors(row, {"SYNTH_STATE": state}) == []


def test_legacy_real_relation_is_unresolved_until_an_accepted_typed_receipt_exists() -> None:
    legacy_child = _row_payload(
        code="LEGACY_CHILD",
        geographic_kind="municipality",
        relation=_inherited("state", "LEGACY_PARENT"),
    )
    legacy_child.pop("authority_relation")

    row = CoverageRegistryRow.model_validate(legacy_child)

    assert row.parent_jurisdiction_code == "LEGACY_PARENT"
    assert row.municipal_audit_decision == "covered_by_parent"
    assert row.authority_relation.relation == "unresolved"
    assert row.authority_relation.aggregation_disposition == "refuse"


def test_legacy_registry_roundtrip_materializes_unresolved_without_inference(tmp_path: Path) -> None:
    legacy_child = _row_payload(
        code="LEGACY_CHILD",
        geographic_kind="municipality",
        relation=_inherited("state", "LEGACY_PARENT"),
    )
    legacy_child.pop("authority_relation")
    registry = CoverageRegistry.model_validate({"rows": [legacy_child]})

    output_path = write_registry(tmp_path / "coverage-registry.json", registry)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    reloaded = load_registry(output_path)

    assert written["rows"][0]["authority_relation"] == {
        "relation": "unresolved",
        "candidate_authorities": [
            {"kind": "state", "code": "LEGACY_PARENT", "name": None},
            {"kind": "municipality", "code": "LEGACY_CHILD", "name": None},
        ],
        "reason": "Legacy compatibility fields do not carry an accepted typed filing-authority receipt.",
        "aggregation_disposition": "refuse",
    }
    assert reloaded == registry


def test_accepted_ny_nyc_and_wa_seattle_partitions_are_exact() -> None:
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    rows = {row.jurisdiction_code: row for row in registry.rows}
    nyc = rows["NY_NEW_YORK"]
    seattle = rows["WA_SEATTLE"]

    assert nyc.municipal_audit_decision == "independent_target"
    assert nyc.authority_relation.relation == "partitioned_overlapping"
    assert [(row.kind, row.code) for row in nyc.authority_relation.authorities] == [
        ("state", "NY"),
        ("municipality", "NY_NEW_YORK"),
    ]
    assert [row.authority.code for row in nyc.authority_relation.precedence] == [
        "NY_NEW_YORK",
        "NY",
    ]
    assert [row.scope for row in nyc.authority_relation.partitions] == [
        (
            "For registrations and filings made on or after 2020-04-27, NYC CFB substitutes only for "
            "candidates and their authorized political committees for Mayor, Public Advocate, Comptroller, "
            "Borough President, and City Council."
        ),
        (
            "Other NYC office and committee classes remain NYSBOE, applicable federal, or separately proved; "
            "CFB and NYSBOE independent-expenditure or municipal-ballot obligations overlap only when both "
            "systems' definitions and thresholds apply."
        ),
    ]
    assert nyc.authority_relation.deduplication.disposition == "refuse_combination"
    assert nyc.authority_relation.refusals == [
        "Education Law elections",
        "special-district elections",
        "fire-district elections",
        "library-district elections",
    ]
    assert nyc.authority_relation.evidence.receipt == "receipts/wave-01-ny-nyc-receipt.json"
    assert (
        nyc.authority_relation.evidence.receipt_sha256
        == "40aa23427cd6ba0a817d615b8b1b6e29b7903de368705fb0d0a26bb11090cc01"
    )
    assert (
        nyc.authority_relation.evidence.packet_sha256
        == "2bf162ae4f2051d86cb9cb39ff100e568fb4e52153e7ee7205fc19349de39731"
    )
    assert seattle.municipal_audit_decision == "covered_by_parent"
    assert seattle.authority_relation.relation == "partitioned_overlapping"
    assert [(row.kind, row.code, row.name) for row in seattle.authority_relation.authorities] == [
        ("state", "WA", None),
        ("named_other", "WA_SEATTLE_CITY_CLERK", "Seattle City Clerk"),
        ("named_other", "WA_SEEC", "Seattle Ethics and Elections Commission"),
    ]
    assert [row.authority.code for row in seattle.authority_relation.precedence] == [
        "WA",
        "WA_SEATTLE_CITY_CLERK",
        "WA_SEEC",
    ]
    assert [row.authority.code for row in seattle.authority_relation.partitions] == [
        "WA",
        "WA_SEATTLE_CITY_CLERK",
        "WA_SEEC",
    ]
    assert seattle.authority_relation.deduplication.disposition == "refuse_combination"
    assert seattle.authority_relation.evidence.receipt == "receipts/wave-01-wa-seattle-receipt.json"
    assert (
        seattle.authority_relation.evidence.receipt_sha256
        == "5d0d37182299b1261a86ea7fd02338598f91d32714770dea7923e16e17fda669"
    )
    assert (
        seattle.authority_relation.evidence.packet_sha256
        == "c86804d46312d5fb524a8f2c1f56f30413dc6d200a24086d00b69c9e011d50c8"
    )
    assert seattle.authority_relation.evidence.aggregate_receipt == "receipts/wave-01-controls-receipt.json"
    assert (
        seattle.authority_relation.evidence.aggregate_receipt_sha256
        == "ce959a6cd8aba1517c3fd320546caccce2aecbbb0756fce9cf308dbd0d52fd7a"
    )


def test_legacy_municipality_fields_do_not_choose_the_typed_relation() -> None:
    payload = _row_payload(
        code="SYNTH_CITY",
        geographic_kind="municipality",
        relation=_independent("municipality", "SYNTH_CITY"),
    )
    payload["parent_jurisdiction_code"] = "SYNTH_STATE"
    payload["municipal_audit_decision"] = "covered_by_parent"

    row = CoverageRegistryRow.model_validate(payload)

    assert row.municipal_audit_decision == "covered_by_parent"
    assert row.authority_relation.relation == "independent"


def test_overlap_fixture_is_not_mutated_by_validation() -> None:
    relation = _overlap_relation()
    before = deepcopy(relation)

    CoverageRegistryRow.model_validate(_row_payload(code="SYNTH_COUNTY", geographic_kind="county", relation=relation))

    assert relation == before
