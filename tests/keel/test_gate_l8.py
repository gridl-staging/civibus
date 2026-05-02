from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import pytest
import yaml

from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.scoring import score_entities


REPO_ROOT = Path(__file__).resolve().parents[2]
L8_SCHEMA_PATH = REPO_ROOT / "evidence_schemas" / "L8.json"
REGRESSION_PAIRS_PATH = REPO_ROOT / "tests" / "er_regression_pairs.yaml"
FALSE_POSITIVE_CORPUS_PATH = REPO_ROOT / "tests" / "er_false_positive_corpus.yaml"
_GATE_MODULE_CANDIDATES = (
    "core.entity_resolution.l8_regression",
    "core.keel_gate_l8",
)
_NC_MUST_MATCH_CASE_IDS = (
    "nc_organization_adams_for_nc_house_suffix_normalization",
    "nc_person_julia_c_howard_middle_initial_normalization",
)
_NC_MUST_NOT_MATCH_CASE_IDS = ("nc_person_julia_howard_vs_mitchell_setzer_distinct_legislators",)


class RegressionPairCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    entity_type: Literal["person", "organization"]
    left_entity: dict[str, Any] = Field(min_length=1)
    right_entity: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    source_notes: list[str] = Field(min_length=1)


class RegressionPairsFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    must_match: list[RegressionPairCase] = Field(min_length=1)
    must_not_match: list[RegressionPairCase] = Field(min_length=1)


class FalsePositiveCorpusCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str = Field(min_length=1)
    entity_type: Literal["person", "organization"]
    fixture_payload: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    source_notes: list[str] = Field(min_length=1)


class FalsePositiveCorpusFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    cases: list[FalsePositiveCorpusCase] = Field(min_length=1)


def _load_yaml_payload(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_regression_pairs_fixture() -> RegressionPairsFixture:
    return RegressionPairsFixture.model_validate(_load_yaml_payload(REGRESSION_PAIRS_PATH))


def _load_false_positive_corpus_fixture() -> FalsePositiveCorpusFixture:
    return FalsePositiveCorpusFixture.model_validate(_load_yaml_payload(FALSE_POSITIVE_CORPUS_PATH))


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_schema_errors(*, schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    return [error.message for error in validator.iter_errors(payload)]


def _sample_l8_payload() -> dict[str, Any]:
    return {
        "layer": "L8",
        "scope": "person",
        "schema_version": 1,
        "produced_at_utc": "2026-04-24T18:30:00Z",
        "repo_sha": "4a64e348",
        "gate_command": "uv run --extra dev --extra entity-resolution pytest tests/keel/test_gate_l8.py -q",
        "status": "fail",
        "regression_pairs_checked": 2,
        "must_match_violations": 1,
        "must_not_match_violations": 1,
        "pair_results": [
            {
                "case_id": "person_same_name_cross_source",
                "expected_relation": "must_match",
                "entity_type": "person",
                "entity_id_a": "e6d9b7ad-0ca0-53d6-b0bb-2b43d4684d8a",
                "entity_id_b": "f93cf402-fb9c-56dd-b4f4-54a3f3543ee2",
                "decision": "no_match",
                "confidence": 0.42,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
                "passed": False,
            }
        ],
        "false_positive_summary": {
            "cases_evaluated": 1,
            "flagged_false_positives": 0,
            "flagged_case_ids": [],
            "false_positive_rate": 0.0,
        },
    }


def _stable_entity_id(case_id: str, side: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"l8-regression:{case_id}:{side}"))


def _classify_case_with_confidence(
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: RegressionPairCase,
    confidence: float,
) -> dict[str, Any]:
    entity_id_a = _stable_entity_id(case.case_id, "left")
    entity_id_b = _stable_entity_id(case.case_id, "right")

    rows = [
        {
            "id": entity_id_a,
            "canonical_name": str(case.left_entity.get("canonical_name", case.case_id)),
        },
        {
            "id": entity_id_b,
            "canonical_name": str(case.right_entity.get("canonical_name", case.case_id)),
        },
    ]

    ordered_pair = (min(entity_id_a, entity_id_b), max(entity_id_a, entity_id_b))

    monkeypatch.setattr(
        "core.entity_resolution.scoring.extract_rows_for_matching",
        lambda _conn, _entity_type: rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.run_deterministic_rules",
        lambda _conn, _entity_type: [],
    )

    def _fake_score_with_splink(unresolved_rows: list[dict[str, Any]], entity_type: str) -> list[dict[str, Any]]:
        assert entity_type == case.entity_type
        assert [row["id"] for row in unresolved_rows] == [entity_id_a, entity_id_b]
        return [
            {
                "entity_id_a": ordered_pair[0],
                "entity_id_b": ordered_pair[1],
                "confidence": confidence,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
            }
        ]

    monkeypatch.setattr(
        "core.entity_resolution.scoring.score_with_splink",
        _fake_score_with_splink,
    )

    scored_pairs = score_entities(object(), case.entity_type)
    classified_pairs = classify_scored_pairs(scored_pairs)
    assert len(classified_pairs) == 1

    classified = classified_pairs[0]
    return {
        "case_id": case.case_id,
        "expected_relation": "must_match" if confidence < 0.5 else "must_not_match",
        "entity_type": case.entity_type,
        "entity_id_a": classified["entity_id_a"],
        "entity_id_b": classified["entity_id_b"],
        "decision": classified["decision"],
        "confidence": classified["confidence"],
        "decision_method": classified["decision_method"],
        "decided_by": classified["decided_by"],
    }


def _load_regression_evaluator() -> Any:
    module = _load_gate_module()

    evaluator = getattr(module, "evaluate_regression_pairs", None)
    if not callable(evaluator):
        pytest.fail(f"{module.__name__}.evaluate_regression_pairs must be implemented for L8 gate checks")
    return evaluator


def _load_gate_module() -> Any:
    import_errors: list[str] = []
    for module_name in _GATE_MODULE_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            import_errors.append(str(error))
            continue
        run_gate = getattr(module, "run_l8_regression_gate", None)
        if callable(run_gate):
            return module
    pytest.fail(
        "L8 gate module is missing callable run_l8_regression_gate. "
        f"Candidates: {_GATE_MODULE_CANDIDATES}. Errors: {import_errors}"
    )


def test_l8_gate_prefers_er_owned_module_boundary() -> None:
    module = _load_gate_module()
    assert module.__name__ == "core.entity_resolution.l8_regression"


def test_l8_schema_round_trip_for_contract_payload() -> None:
    schema = _load_schema(L8_SCHEMA_PATH)
    payload = _sample_l8_payload()

    assert _json_schema_errors(schema=schema, payload=payload) == []

    round_trip_payload = json.loads(json.dumps(payload))
    assert _json_schema_errors(schema=schema, payload=round_trip_payload) == []


@pytest.mark.parametrize(
    "required_field",
    [
        "case_id",
        "entity_type",
        "left_entity",
        "right_entity",
        "rationale",
        "source_notes",
    ],
)
def test_er_regression_pairs_required_field_validation(required_field: str) -> None:
    payload = _load_yaml_payload(REGRESSION_PAIRS_PATH)
    RegressionPairsFixture.model_validate(payload)

    mutated = json.loads(json.dumps(payload))
    del mutated["must_match"][0][required_field]

    with pytest.raises(ValidationError):
        RegressionPairsFixture.model_validate(mutated)


def test_l8_contract_inputs_are_deterministically_ordered() -> None:
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()

    must_match_ids = [case.case_id for case in regression_pairs.must_match]
    must_not_match_ids = [case.case_id for case in regression_pairs.must_not_match]
    combined_ids = must_match_ids + must_not_match_ids

    assert must_match_ids == sorted(must_match_ids)
    assert must_not_match_ids == sorted(must_not_match_ids)
    assert len(combined_ids) == len(set(combined_ids))

    corpus_ids = [case.corpus_id for case in false_positive_corpus.cases]
    assert corpus_ids == sorted(corpus_ids)
    assert len(corpus_ids) == len(set(corpus_ids))


def test_l8_regression_fixture_includes_named_nc_cases() -> None:
    regression_pairs = _load_regression_pairs_fixture()
    must_match_ids = {case.case_id for case in regression_pairs.must_match}
    must_not_match_ids = {case.case_id for case in regression_pairs.must_not_match}

    for case_id in _NC_MUST_MATCH_CASE_IDS:
        assert case_id in must_match_ids
    for case_id in _NC_MUST_NOT_MATCH_CASE_IDS:
        assert case_id in must_not_match_ids


def test_l8_gate_fails_when_curated_must_match_pair_is_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regression_pairs = _load_regression_pairs_fixture()
    case = regression_pairs.must_match[0]

    split_result = _classify_case_with_confidence(
        monkeypatch,
        case=case,
        confidence=0.42,
    )
    split_result["expected_relation"] = "must_match"

    evaluator = _load_regression_evaluator()
    violations = evaluator(
        pair_results=[split_result],
        regression_pairs=regression_pairs.model_dump(mode="python"),
    )

    violating_case_ids = {item["case_id"] for item in violations["must_match_failures"]}
    assert case.case_id in violating_case_ids


def test_l8_regression_curated_exact_must_match_case_scores_as_match() -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    case = next(case for case in regression_pairs.must_match if case.case_id == "person_cross_source_exact_name_address")

    result = module.score_regression_pair_case(
        case=case,
        expected_relation="must_match",
    )

    assert result["case_id"] == "person_cross_source_exact_name_address"
    assert result["decision"] == "match"
    assert result["passed"] is True


@pytest.mark.parametrize(
    "case_id",
    [
        "organization_suffix_normalization",
        "nc_organization_adams_for_nc_house_suffix_normalization",
        "nc_person_julia_c_howard_middle_initial_normalization",
    ],
)
def test_l8_regression_curated_normalization_must_match_cases_score_as_match(case_id: str) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    case = next(case for case in regression_pairs.must_match if case.case_id == case_id)

    result = module.score_regression_pair_case(
        case=case,
        expected_relation="must_match",
    )

    assert result["decision"] == "match"
    assert result["passed"] is True


def test_l8_regression_distinct_middle_initial_case_remains_non_match() -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    case = next(case for case in regression_pairs.must_not_match if case.case_id == "person_same_name_different_middle_initial")

    result = module.score_regression_pair_case(
        case=case,
        expected_relation="must_not_match",
    )

    assert result["decision"] != "match"
    assert result["passed"] is True


def test_l8_regression_curated_weak_person_identity_does_not_short_circuit_to_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    case = RegressionPairCase(
        case_id="person_same_name_state_missing_middle_conflicting_identity",
        entity_type="person",
        left_entity={
            "canonical_name": "Jordan Lee",
            "primary_address": "100 Main St, Raleigh, NC 27601",
            "source_record_key": "NC-CAN-1001",
        },
        right_entity={
            "canonical_name": "Jordan Lee",
            "primary_address": "200 Elm St, Durham, NC 27701",
            "source_record_key": "NC-CAN-9901",
        },
        rationale="Same first/last/state without shared address or identifier must not auto-merge.",
        source_notes=["synthetic_guard_case"],
    )
    entity_id_a = _stable_entity_id(case.case_id, "left")
    entity_id_b = _stable_entity_id(case.case_id, "right")
    ordered_pair = (min(entity_id_a, entity_id_b), max(entity_id_a, entity_id_b))

    monkeypatch.setattr(
        module,
        "score_rows",
        lambda _rows, _entity_type, deterministic_pairs: [
            {
                "entity_id_a": ordered_pair[0],
                "entity_id_b": ordered_pair[1],
                "confidence": 0.12,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "classify_scored_pairs",
        lambda _scored_pairs, auto_merge_threshold: [
            {
                "entity_id_a": ordered_pair[0],
                "entity_id_b": ordered_pair[1],
                "decision": "no_match",
                "confidence": 0.12,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
            }
        ],
    )

    result = module.score_regression_pair_case(
        case=case,
        expected_relation="must_not_match",
    )

    assert result["decision"] == "no_match"
    assert result["decided_by"] == "splink_v1"
    assert result["passed"] is True


def test_l8_gate_fails_when_curated_must_not_match_pair_merges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regression_pairs = _load_regression_pairs_fixture()
    case = regression_pairs.must_not_match[0]

    merged_result = _classify_case_with_confidence(
        monkeypatch,
        case=case,
        confidence=0.99,
    )
    merged_result["expected_relation"] = "must_not_match"

    evaluator = _load_regression_evaluator()
    violations = evaluator(
        pair_results=[merged_result],
        regression_pairs=regression_pairs.model_dump(mode="python"),
    )

    violating_case_ids = {item["case_id"] for item in violations["must_not_match_failures"]}
    assert case.case_id in violating_case_ids


def test_l8_gate_writes_evidence_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()
    output_path = tmp_path / "regression_run.json"

    def _fake_score_regression_pair_case(*, case: RegressionPairCase, expected_relation: str, **_: Any) -> dict[str, Any]:
        decision = "match" if expected_relation == "must_match" else "no_match"
        return {
            "case_id": case.case_id,
            "expected_relation": expected_relation,
            "entity_type": case.entity_type,
            "entity_id_a": _stable_entity_id(case.case_id, "left"),
            "entity_id_b": _stable_entity_id(case.case_id, "right"),
            "decision": decision,
            "confidence": 0.99 if decision == "match" else 0.2,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        }

    monkeypatch.setattr(module, "score_regression_pair_case", _fake_score_regression_pair_case)
    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, **_: {
            "case_id": case.corpus_id,
            "decision": "no_match",
            "confidence": 0.12,
            "flagged_false_positive": False,
        },
    )

    payload = module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=output_path,
        produced_at=datetime(2026, 4, 24, 21, 15, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
    )

    assert output_path.exists()
    assert payload == json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["regression_pairs_checked"] == len(regression_pairs.must_match) + len(regression_pairs.must_not_match)
    assert payload["false_positive_summary"]["cases_evaluated"] == len(false_positive_corpus.cases)
    assert _json_schema_errors(schema=_load_schema(L8_SCHEMA_PATH), payload=payload) == []


def test_l8_gate_records_pair_level_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()

    def _fake_score_regression_pair_case(*, case: RegressionPairCase, expected_relation: str, **_: Any) -> dict[str, Any]:
        if case.case_id == regression_pairs.must_match[0].case_id:
            return {
                "case_id": case.case_id,
                "expected_relation": expected_relation,
                "entity_type": case.entity_type,
                "entity_id_a": _stable_entity_id(case.case_id, "left"),
                "entity_id_b": _stable_entity_id(case.case_id, "right"),
                "decision": "no_match",
                "confidence": 0.41,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
                "passed": False,
            }
        return {
            "case_id": case.case_id,
            "expected_relation": expected_relation,
            "entity_type": case.entity_type,
            "entity_id_a": _stable_entity_id(case.case_id, "left"),
            "entity_id_b": _stable_entity_id(case.case_id, "right"),
            "decision": "no_match" if expected_relation == "must_not_match" else "match",
            "confidence": 0.96,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        }

    monkeypatch.setattr(module, "score_regression_pair_case", _fake_score_regression_pair_case)
    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, **_: {
            "case_id": case.corpus_id,
            "decision": "no_match",
            "confidence": 0.08,
            "flagged_false_positive": False,
        },
    )

    payload = module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "regression_run.json",
        produced_at=datetime(2026, 4, 24, 21, 20, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
    )

    assert payload["status"] == "fail"
    assert payload["must_match_violations"] == 1
    assert payload["must_not_match_violations"] == 0
    assert [result["case_id"] for result in payload["pair_results"]] == sorted(
        result["case_id"] for result in payload["pair_results"]
    )
    violating_result = next(result for result in payload["pair_results"] if not result["passed"])
    assert violating_result["case_id"] == regression_pairs.must_match[0].case_id
    assert violating_result["expected_relation"] == "must_match"
    assert violating_result["decision"] == "no_match"


def test_l8_gate_inversion_failure_surfaces_named_nc_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()
    target_case_id = "nc_person_julia_c_howard_middle_initial_normalization"

    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, **_: {
            "case_id": case.corpus_id,
            "decision": "no_match",
            "confidence": 0.11,
            "flagged_false_positive": False,
        },
    )

    def _fake_score_regression_pair_case(*, case: RegressionPairCase, expected_relation: str, **_: Any) -> dict[str, Any]:
        if case.case_id == target_case_id:
            return {
                "case_id": case.case_id,
                "expected_relation": expected_relation,
                "entity_type": case.entity_type,
                "entity_id_a": _stable_entity_id(case.case_id, "left"),
                "entity_id_b": _stable_entity_id(case.case_id, "right"),
                "decision": "no_match",
                "confidence": 0.43,
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
                "passed": False,
            }
        return {
            "case_id": case.case_id,
            "expected_relation": expected_relation,
            "entity_type": case.entity_type,
            "entity_id_a": _stable_entity_id(case.case_id, "left"),
            "entity_id_b": _stable_entity_id(case.case_id, "right"),
            "decision": "match" if expected_relation == "must_match" else "no_match",
            "confidence": 0.98,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        }

    monkeypatch.setattr(module, "score_regression_pair_case", _fake_score_regression_pair_case)

    payload = module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "inversion.json",
        produced_at=datetime(2026, 4, 29, 14, 0, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
    )

    evaluator = _load_regression_evaluator()
    violations = evaluator(
        pair_results=payload["pair_results"],
        regression_pairs=regression_pairs.model_dump(mode="python"),
    )
    assert target_case_id in {case["case_id"] for case in violations["must_match_failures"]}
    target_result = next(result for result in payload["pair_results"] if result["case_id"] == target_case_id)
    assert payload["status"] == "fail"
    assert target_result["passed"] is False


def test_l8_gate_false_positive_summary_is_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()

    monkeypatch.setattr(
        module,
        "score_regression_pair_case",
        lambda *, case, expected_relation, **_: {
            "case_id": case.case_id,
            "expected_relation": expected_relation,
            "entity_type": case.entity_type,
            "entity_id_a": _stable_entity_id(case.case_id, "left"),
            "entity_id_b": _stable_entity_id(case.case_id, "right"),
            "decision": "match" if expected_relation == "must_match" else "no_match",
            "confidence": 0.98,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, **_: {
            "case_id": case.corpus_id,
            "decision": "match" if case.corpus_id.startswith("person_") else "no_match",
            "confidence": 0.97 if case.corpus_id.startswith("person_") else 0.21,
            "flagged_false_positive": case.corpus_id.startswith("person_"),
        },
    )

    first_payload = module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "first.json",
        produced_at=datetime(2026, 4, 24, 21, 25, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
    )
    second_payload = module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "second.json",
        produced_at=datetime(2026, 4, 24, 21, 25, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
    )

    assert first_payload["false_positive_summary"] == second_payload["false_positive_summary"]
    assert first_payload["false_positive_summary"] == {
        "cases_evaluated": len(false_positive_corpus.cases),
        "flagged_false_positives": 1,
        "flagged_case_ids": ["person_public_figure_name_collision"],
        "false_positive_rate": 0.5,
    }


def test_l8_gate_resolves_threshold_override_once_and_threads_to_every_classification_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()
    resolved_threshold_calls: list[float | None] = []
    regression_thresholds: list[float | None] = []
    corpus_thresholds: list[float | None] = []

    monkeypatch.setattr(
        module,
        "resolve_auto_merge_threshold",
        lambda override: resolved_threshold_calls.append(override) or 0.97,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "score_regression_pair_case",
        lambda *, auto_merge_threshold, **kwargs: regression_thresholds.append(auto_merge_threshold)
        or {
            "case_id": kwargs["case"].case_id,
            "expected_relation": kwargs["expected_relation"],
            "entity_type": kwargs["case"].entity_type,
            "entity_id_a": _stable_entity_id(kwargs["case"].case_id, "left"),
            "entity_id_b": _stable_entity_id(kwargs["case"].case_id, "right"),
            "decision": "match" if kwargs["expected_relation"] == "must_match" else "no_match",
            "confidence": 0.99,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, auto_merge_threshold, **_: corpus_thresholds.append(auto_merge_threshold)
        or {
            "case_id": case.corpus_id,
            "decision": "no_match",
            "confidence": 0.11,
            "flagged_false_positive": False,
        },
    )

    module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "regression_run.json",
        produced_at=datetime(2026, 4, 24, 21, 40, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_gate_l8",
        auto_merge_threshold=0.94,
    )

    assert resolved_threshold_calls == [0.94]
    expected_pair_evaluations = len(regression_pairs.must_match) + len(regression_pairs.must_not_match)
    assert regression_thresholds == [0.97] * expected_pair_evaluations
    assert corpus_thresholds == [0.97] * len(false_positive_corpus.cases)


def test_l8_gate_threads_explicit_probabilistic_settings_only_to_person_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_gate_module()
    regression_pairs = _load_regression_pairs_fixture()
    false_positive_corpus = _load_false_positive_corpus_fixture()
    candidate_settings = {"candidate_id": "stage3-ncga-house-01"}
    observed_pair_settings: list[tuple[str, object | None]] = []
    observed_corpus_settings: list[tuple[str, object | None]] = []

    monkeypatch.setattr(
        module,
        "score_regression_pair_case",
        lambda *, probabilistic_settings=None, case, expected_relation, **_: observed_pair_settings.append(
            (case.entity_type, probabilistic_settings)
        )
        or {
            "case_id": case.case_id,
            "expected_relation": expected_relation,
            "entity_type": case.entity_type,
            "entity_id_a": _stable_entity_id(case.case_id, "left"),
            "entity_id_b": _stable_entity_id(case.case_id, "right"),
            "decision": "match" if expected_relation == "must_match" else "no_match",
            "confidence": 0.99,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        module,
        "score_false_positive_case",
        lambda *, case, probabilistic_settings=None, **_: observed_corpus_settings.append(
            (case.entity_type, probabilistic_settings)
        )
        or {
            "case_id": case.corpus_id,
            "decision": "no_match",
            "confidence": 0.11,
            "flagged_false_positive": False,
        },
    )

    module.run_l8_regression_gate(
        regression_pairs=regression_pairs.model_dump(mode="python"),
        false_positive_corpus=false_positive_corpus.model_dump(mode="python"),
        artifact_path=tmp_path / "regression_run.json",
        probabilistic_settings=candidate_settings,
    )

    for entity_type, settings in observed_pair_settings:
        if entity_type == "person":
            assert settings == candidate_settings
        else:
            assert settings is None
    for entity_type, settings in observed_corpus_settings:
        if entity_type == "person":
            assert settings == candidate_settings
        else:
            assert settings is None
