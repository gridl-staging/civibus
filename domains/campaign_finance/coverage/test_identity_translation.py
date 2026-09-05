from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    IdentityTranslation,
    IdentityTranslationContradictionError,
    IdentityTranslationKindMismatchError,
    IdentityTranslationMultipleError,
    IdentityTranslationNotFoundError,
    ScopedIdentity,
    load_registry,
    translate_identity,
)


def _registry_row(*, relation: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "jurisdiction_code": "SYNTH_GEO",
        "name": "Synthetic geography",
        "jurisdiction_type": "state",
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-08-28",
        "covers_sub_jurisdictions": False,
        "source_count": 1,
        "source_names": ["Synthetic source"],
        "runner_wired": False,
        "tier": None,
        "evidence_summary": None,
        "operational_reason": None,
        "next_action": None,
        "evidence_date": "2026-08-28",
        **({"authority_relation": relation} if relation is not None else {}),
    }


def _identity(domain: str, kind: str, value: str) -> ScopedIdentity:
    return ScopedIdentity.model_validate({"domain": domain, "kind": kind, "value": value})


def _complete_translation(
    *,
    route_value: str = "/synthetic/state",
) -> IdentityTranslation:
    return IdentityTranslation.model_validate(
        {
            "geographic_subject": {
                "domain": "geographic_subject",
                "kind": "state",
                "value": "SYNTH_GEO",
            },
            "filing_authority": {
                "domain": "filing_authority",
                "kind": "state",
                "value": "SYNTH_AUTHORITY",
            },
            "acquisition_scope": {
                "domain": "acquisition_scope",
                "kind": "state",
                "value": "SYNTH_CONFIG",
            },
            "provenance_scope": {
                "domain": "provenance_scope",
                "kind": "state",
                "value": "synthetic/source",
            },
            "public_route": {
                "domain": "public_route",
                "kind": "state",
                "value": route_value,
            },
        }
    )


def test_translation_keeps_all_five_identity_domains_distinct() -> None:
    translation = _complete_translation()
    source = _identity("acquisition_scope", "state", "SYNTH_CONFIG")

    assert translate_identity(
        source,
        target_domain="geographic_subject",
        translations=[translation],
    ) == _identity("geographic_subject", "state", "SYNTH_GEO")
    assert translate_identity(
        source,
        target_domain="filing_authority",
        translations=[translation],
    ) == _identity("filing_authority", "state", "SYNTH_AUTHORITY")
    assert translate_identity(
        source,
        target_domain="provenance_scope",
        translations=[translation],
    ) == _identity("provenance_scope", "state", "synthetic/source")
    assert translate_identity(
        source,
        target_domain="public_route",
        translations=[translation],
    ) == _identity("public_route", "state", "/synthetic/state")


def test_translation_refuses_zero_matches() -> None:
    with pytest.raises(IdentityTranslationNotFoundError, match="zero"):
        translate_identity(
            _identity("acquisition_scope", "state", "MISSING"),
            target_domain="geographic_subject",
            translations=[_complete_translation()],
        )


def test_translation_refuses_multiple_identical_matches() -> None:
    translation = _complete_translation()

    with pytest.raises(IdentityTranslationMultipleError, match="multiple"):
        translate_identity(
            _identity("acquisition_scope", "state", "SYNTH_CONFIG"),
            target_domain="geographic_subject",
            translations=[translation, translation.model_copy(deep=True)],
        )


def test_translation_refuses_kind_mismatch() -> None:
    with pytest.raises(IdentityTranslationKindMismatchError, match="kind mismatch"):
        translate_identity(
            _identity("acquisition_scope", "county", "SYNTH_CONFIG"),
            target_domain="geographic_subject",
            translations=[_complete_translation()],
        )


def test_translation_refuses_contradictory_matches() -> None:
    first = _complete_translation(route_value="/synthetic/one")
    second = _complete_translation(route_value="/synthetic/two")

    with pytest.raises(IdentityTranslationContradictionError, match="contradictory"):
        translate_identity(
            _identity("acquisition_scope", "state", "SYNTH_CONFIG"),
            target_domain="public_route",
            translations=[first, second],
        )


def test_translation_refuses_absent_target_domain() -> None:
    partial = IdentityTranslation.model_validate(
        {
            "geographic_subject": {
                "domain": "geographic_subject",
                "kind": "municipality",
                "value": "SYNTH_CITY",
            },
            "public_route": {
                "domain": "public_route",
                "kind": "municipality",
                "value": "/synthetic/city",
            },
        }
    )

    with pytest.raises(IdentityTranslationNotFoundError, match="filing_authority"):
        translate_identity(
            partial.geographic_subject,
            target_domain="filing_authority",
            translations=[partial],
        )


def test_identity_slot_rejects_wrong_domain_and_named_other_geography() -> None:
    payload = _complete_translation().model_dump(mode="json")
    payload["geographic_subject"]["domain"] = "filing_authority"
    with pytest.raises(ValidationError, match="geographic_subject"):
        IdentityTranslation.model_validate(payload)

    with pytest.raises(ValidationError, match="named_other.*geographic_subject"):
        ScopedIdentity.model_validate(
            {
                "domain": "geographic_subject",
                "kind": "named_other",
                "value": "SYNTH_OTHER",
                "name": "Synthetic Other Authority",
            }
        )


def test_registry_translation_requires_one_matching_geographic_subject_row() -> None:
    translation = _complete_translation()

    with pytest.raises(ValidationError, match="geographic_subject.*does not resolve"):
        CoverageRegistry.model_validate(
            {
                "identity_translations": [translation.model_dump(mode="json")],
                "rows": [],
            }
        )


def test_registry_translation_refuses_filing_authority_for_unresolved_relation() -> None:
    with pytest.raises(ValidationError, match="filing_authority.*unresolved"):
        CoverageRegistry.model_validate(
            {
                "identity_translations": [_complete_translation().model_dump(mode="json")],
                "rows": [_registry_row()],
            }
        )


def test_registry_translation_accepts_filing_authority_from_accepted_relation() -> None:
    translation = _complete_translation().model_dump(mode="json")
    translation["filing_authority"] = {
        "domain": "filing_authority",
        "kind": "named_other",
        "value": "SYNTH_AUTHORITY",
        "name": "Synthetic Filing Authority",
    }
    registry = CoverageRegistry.model_validate(
        {
            "identity_translations": [translation],
            "rows": [
                _registry_row(
                    relation={
                        "relation": "independent",
                        "authority": {
                            "kind": "named_other",
                            "code": "SYNTH_AUTHORITY",
                            "name": "Synthetic Filing Authority",
                        },
                    }
                )
            ],
        }
    )

    assert registry.identity_translations[0].filing_authority is not None


def test_registry_route_compatibility_does_not_flatten_overlapping_seattle_authorities() -> None:
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    seattle_route = _identity(
        "public_route",
        "municipality",
        "/state/WA/municipality/seattle",
    )
    geographic_subject = translate_identity(
        seattle_route,
        target_domain="geographic_subject",
        translations=registry.identity_translations,
    )

    assert geographic_subject == _identity(
        "geographic_subject",
        "municipality",
        "WA_SEATTLE",
    )
    with pytest.raises(IdentityTranslationNotFoundError, match="filing_authority"):
        translate_identity(
            seattle_route,
            target_domain="filing_authority",
            translations=registry.identity_translations,
        )
