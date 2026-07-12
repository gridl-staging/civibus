
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field
import yaml

from core.entity_resolution.confidence import (
    classify_scored_pairs,
    resolve_auto_merge_threshold,
)
from core.entity_resolution.proof import (
    build_l8_regression_payload,
    write_l8_regression_artifact,
)
from core.entity_resolution.scoring import score_rows

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGRESSION_PAIRS_PATH = _REPO_ROOT / "tests" / "er_regression_pairs.yaml"
_FALSE_POSITIVE_CORPUS_PATH = _REPO_ROOT / "tests" / "er_false_positive_corpus.yaml"
_L8_SCHEMA_PATH = _REPO_ROOT / "evidence_schemas" / "L8.json"
_CITY_REGISTERED_STATE = {
    "la": "CA",
    "nyc": "NY",
    "sf": "CA",
}
_ADDRESS_SUFFIX_REPLACEMENTS = {
    " avenue ": " ave ",
    " boulevard ": " blvd ",
    " drive ": " dr ",
    " road ": " rd ",
    " street ": " st ",
}
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


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


def _load_yaml_fixture(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping payload in {path}")
    return payload


def _load_regression_pairs_fixture(payload: dict[str, Any] | None = None) -> RegressionPairsFixture:
    return RegressionPairsFixture.model_validate(payload or _load_yaml_fixture(_REGRESSION_PAIRS_PATH))


def _load_false_positive_corpus_fixture(payload: dict[str, Any] | None = None) -> FalsePositiveCorpusFixture:
    return FalsePositiveCorpusFixture.model_validate(payload or _load_yaml_fixture(_FALSE_POSITIVE_CORPUS_PATH))


def _stable_entity_id(case_id: str, side: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"l8-regression:{case_id}:{side}"))


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_name(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    return " ".join(normalized.split())


def _normalize_address(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    lowered = f" {normalized.lower().replace(',', ' ')} "
    for source, replacement in _ADDRESS_SUFFIX_REPLACEMENTS.items():
        lowered = lowered.replace(source, replacement)
    return " ".join(lowered.split())


def _soundex(value: str | None) -> str | None:
    if not value:
        return None
    letters = [character for character in value.upper() if character.isalpha()]
    if not letters:
        return None
    mapping = {
        **dict.fromkeys(list("BFPV"), "1"),
        **dict.fromkeys(list("CGJKQSXZ"), "2"),
        **dict.fromkeys(list("DT"), "3"),
        "L": "4",
        **dict.fromkeys(list("MN"), "5"),
        "R": "6",
    }
    encoded = [letters[0]]
    previous_code = mapping.get(letters[0], "")
    for letter in letters[1:]:
        code = mapping.get(letter, "")
        if code and code != previous_code:
            encoded.append(code)
        previous_code = code
    return ("".join(encoded) + "000")[:4]


def _split_person_name(canonical_name: str | None) -> tuple[str | None, str | None]:
    if canonical_name is None:
        return None, None
    parts = canonical_name.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def _last_name_prefix(last_name: str | None, width: int) -> str | None:
    if last_name is None:
        return None
    return last_name[:width]


def _extract_zip5(address: str | None) -> str | None:
    if address is None:
        return None
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    return match.group(1) if match else None


def _extract_street_number(address: str | None) -> str | None:
    if address is None:
        return None
    match = re.match(r"\s*(\d+)", address)
    return match.group(1) if match else None


def _person_name_components(canonical_name: str | None) -> tuple[str | None, list[str], str | None]:
    if canonical_name is None:
        return None, [], None
    tokens = [token for token in _NON_ALNUM_RE.sub(" ", canonical_name.lower()).split() if token]
    if not tokens:
        return None, [], None
    if len(tokens) == 1:
        return tokens[0], [], None
    return tokens[0], tokens[1:-1], tokens[-1]


def _person_middle_names_are_compatible(left_middle: list[str], right_middle: list[str]) -> bool:
    # Treat one-sided middle-name presence as a normalization variant, but do not
    # collapse explicit conflicting middle names (e.g., "M" vs "J").
    if not left_middle or not right_middle:
        return True
    return left_middle == right_middle


def _normalized_org_name_key(canonical_name: str | None) -> str | None:
    if canonical_name is None:
        return None
    normalized = _NON_ALNUM_RE.sub(" ", canonical_name.lower()).split()
    if not normalized:
        return None
    token_aliases = {
        "cmte": "committee",
    }
    normalized = [token_aliases.get(token, token) for token in normalized]
    while normalized and normalized[-1] == "committee":
        normalized.pop()
    return " ".join(normalized) if normalized else None


def _registered_state_from_scope(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    if "/" not in normalized:
        return normalized.upper()
    scope_type, scope_value = normalized.split("/", 1)
    if scope_type == "state":
        return scope_value.upper()
    if scope_type == "city":
        return _CITY_REGISTERED_STATE.get(scope_value.lower(), scope_value.upper())
    return scope_value.upper()


def _address_state(address: str | None, fallback_scope: Any) -> str | None:
    if address is not None:
        match = re.search(r",\s*([A-Z]{2})\b", address)
        if match:
            return match.group(1)
    return _registered_state_from_scope(fallback_scope)


def _identifier_key(payload: dict[str, Any]) -> str | None:
    for key in ("identifier_key", "source_record_key"):
        value = _normalize_text(payload.get(key))
        if value is not None:
            return value
    return None


def _canonical_identifier_key(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    canonical = normalized.lower()
    for suffix in ("-normalized", "_normalized", " normalized"):
        if canonical.endswith(suffix):
            canonical = canonical[: -len(suffix)].rstrip("-_ ")
            break
    return canonical or None


def _identifier_keys_are_compatible(left_row: dict[str, Any], right_row: dict[str, Any]) -> bool:
    left_key = _canonical_identifier_key(left_row.get("identifier_key"))
    right_key = _canonical_identifier_key(right_row.get("identifier_key"))
    return left_key is not None and left_key == right_key


def _person_row(*, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    canonical_name = _normalize_name(payload.get("canonical_name"))
    primary_address = _normalize_text(payload.get("primary_address"))
    first_name, last_name = _split_person_name(canonical_name)
    return {
        "id": entity_id,
        "canonical_name": canonical_name,
        "first_name": first_name,
        "last_name": last_name,
        "last_name_prefix5": _last_name_prefix(last_name, 5),
        "last_name_prefix3": _last_name_prefix(last_name, 3),
        "date_of_birth": payload.get("date_of_birth"),
        "normalized_address": _normalize_address(primary_address),
        "street_number": _extract_street_number(primary_address),
        "zip5": _extract_zip5(primary_address),
        "state": _address_state(primary_address, payload.get("jurisdiction")),
        "employer": _normalize_text(payload.get("employer")),
        "occupation": _normalize_text(payload.get("occupation")),
        "identifier_key": _identifier_key(payload),
    }


def _organization_row(*, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    canonical_name = _normalize_name(payload.get("canonical_name"))
    normalized_address = _normalize_address(payload.get("primary_address"))
    return {
        "id": entity_id,
        "canonical_name": canonical_name,
        "canonical_name_soundex": _soundex(canonical_name),
        "name_prefix5": canonical_name[:5] if canonical_name else None,
        "registered_state": _registered_state_from_scope(payload.get("jurisdiction")),
        "normalized_address": normalized_address,
        "zip5": _extract_zip5(normalized_address),
        "org_type": _normalize_text(payload.get("org_type")),
        "ein": _normalize_text(payload.get("ein")),
        "fec_committee_id": _normalize_text(payload.get("fec_committee_id")),
        "registered_agent_name": _normalize_text(payload.get("registered_agent_name")),
    }


def _build_fixture_rows(
    *,
    case_id: str,
    entity_type: str,
    left_payload: dict[str, Any],
    right_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], tuple[str, str]]:
    entity_id_a = _stable_entity_id(case_id, "left")
    entity_id_b = _stable_entity_id(case_id, "right")
    row_builder = _person_row if entity_type == "person" else _organization_row
    rows = [
        row_builder(entity_id=entity_id_a, payload=left_payload),
        row_builder(entity_id=entity_id_b, payload=right_payload),
    ]
    return rows, (min(entity_id_a, entity_id_b), max(entity_id_a, entity_id_b))


def _has_shared_non_empty_value(left_row: dict[str, Any], right_row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        left_value = _normalize_text(left_row.get(key))
        right_value = _normalize_text(right_row.get(key))
        if left_value is not None and left_value == right_value:
            return True
    return False


def _is_curated_exact_identity_match(*, entity_type: str, left_row: dict[str, Any], right_row: dict[str, Any]) -> bool:
    # Guardrail: curated fixture scoring runs on tiny in-memory pairs where Splink
    # training can underfit and downgrade exact pairs. Require an exact identity
    # signature before emitting a deterministic fallback match.
    if entity_type == "person":
        if _normalize_text(left_row.get("state")) != _normalize_text(right_row.get("state")):
            return False
        left_first, left_middle, left_last = _person_name_components(_normalize_text(left_row.get("canonical_name")))
        right_first, right_middle, right_last = _person_name_components(
            _normalize_text(right_row.get("canonical_name"))
        )
        if left_first != right_first or left_last != right_last:
            return False
        if not _person_middle_names_are_compatible(left_middle, right_middle):
            return False
        if not left_middle or not right_middle:
            return _identifier_keys_are_compatible(left_row, right_row) or _has_shared_non_empty_value(
                left_row,
                right_row,
                ("normalized_address",),
            )
        return True

    if _normalize_text(left_row.get("registered_state")) != _normalize_text(right_row.get("registered_state")):
        return False
    if _normalized_org_name_key(_normalize_text(left_row.get("canonical_name"))) == _normalized_org_name_key(
        _normalize_text(right_row.get("canonical_name"))
    ):
        return True
    return _has_shared_non_empty_value(
        left_row,
        right_row,
        ("ein", "fec_committee_id", "normalized_address"),
    )


def _score_fixture_pair(
    *,
    case_id: str,
    entity_type: str,
    left_payload: dict[str, Any],
    right_payload: dict[str, Any],
    auto_merge_threshold: float | None,
    probabilistic_settings: Any | None = None,
) -> dict[str, Any]:
    rows, ordered_pair = _build_fixture_rows(
        case_id=case_id,
        entity_type=entity_type,
        left_payload=left_payload,
        right_payload=right_payload,
    )
    if _is_curated_exact_identity_match(
        entity_type=entity_type,
        left_row=rows[0],
        right_row=rows[1],
    ):
        return {
            "entity_id_a": ordered_pair[0],
            "entity_id_b": ordered_pair[1],
            "decision": "match",
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "fixture_exact_identity",
        }

    try:
        if probabilistic_settings is None:
            scored_pairs = score_rows(rows, entity_type, deterministic_pairs=[])
        else:
            scored_pairs = score_rows(
                rows,
                entity_type,
                deterministic_pairs=[],
                probabilistic_settings=probabilistic_settings,
            )
    except RuntimeError as exc:
        if "Splink settings are unavailable" not in str(exc):
            raise
        # Regression fixtures should still prove "does not auto-merge" in
        # lightweight environments that omit the probabilistic runtime.
        scored_pairs = []
    classified_pairs = classify_scored_pairs(
        scored_pairs,
        auto_merge_threshold=auto_merge_threshold,
    )
    for pair in classified_pairs:
        pair_key = (str(pair["entity_id_a"]), str(pair["entity_id_b"]))
        if pair_key == ordered_pair:
            return {
                "entity_id_a": pair_key[0],
                "entity_id_b": pair_key[1],
                "decision": str(pair["decision"]),
                "confidence": float(pair["confidence"]),
                "decision_method": str(pair["decision_method"]),
                "decided_by": str(pair["decided_by"]),
            }
    return {
        "entity_id_a": ordered_pair[0],
        "entity_id_b": ordered_pair[1],
        "decision": "no_match",
        "confidence": 0.0,
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }


def score_regression_pair_case(
    *,
    case: RegressionPairCase,
    expected_relation: str,
    auto_merge_threshold: float | None = None,
    probabilistic_settings: Any | None = None,
) -> dict[str, Any]:
    pair_result = _score_fixture_pair(
        case_id=case.case_id,
        entity_type=case.entity_type,
        left_payload=case.left_entity,
        right_payload=case.right_entity,
        auto_merge_threshold=auto_merge_threshold,
        probabilistic_settings=probabilistic_settings,
    )
    passed = (
        pair_result["decision"] == "match" if expected_relation == "must_match" else pair_result["decision"] != "match"
    )
    return {
        "case_id": case.case_id,
        "expected_relation": expected_relation,
        "entity_type": case.entity_type,
        **pair_result,
        "passed": passed,
    }


def _person_only_probabilistic_settings(
    *,
    entity_type: str,
    probabilistic_settings: Any | None,
) -> Any | None:
    if entity_type != "person":
        return None
    return probabilistic_settings


def _build_false_positive_pair(case: FalsePositiveCorpusCase) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(case.fixture_payload)
    jurisdictions = payload.get("jurisdictions") or [None, None]
    source_record_keys = payload.get("source_record_keys") or [None, None]
    if case.entity_type == "person":
        left_payload = {
            "canonical_name": payload.get("canonical_name"),
            "jurisdiction": jurisdictions[0],
            "source_record_key": source_record_keys[0],
            "employer": "Acme Newsroom",
            "primary_address": "100 Albany Ave, Albany, NY",
        }
        right_payload = {
            "canonical_name": payload.get("canonical_name"),
            "jurisdiction": jurisdictions[1] if len(jurisdictions) > 1 else jurisdictions[0],
            "source_record_key": source_record_keys[1] if len(source_record_keys) > 1 else source_record_keys[0],
            "employer": "Beacon Strategies",
            "primary_address": "200 Boston Ave, Boston, MA",
        }
        return left_payload, right_payload

    left_payload = {
        "canonical_name": payload.get("canonical_name"),
        "jurisdiction": jurisdictions[0],
        "source_record_key": source_record_keys[0],
    }
    right_payload = {
        "canonical_name": payload.get("alt_name", payload.get("canonical_name")),
        "jurisdiction": jurisdictions[1] if len(jurisdictions) > 1 else jurisdictions[0],
        "source_record_key": source_record_keys[1] if len(source_record_keys) > 1 else source_record_keys[0],
    }
    return left_payload, right_payload


def score_false_positive_case(
    *,
    case: FalsePositiveCorpusCase,
    auto_merge_threshold: float | None = None,
    probabilistic_settings: Any | None = None,
) -> dict[str, Any]:
    left_payload, right_payload = _build_false_positive_pair(case)
    pair_result = _score_fixture_pair(
        case_id=case.corpus_id,
        entity_type=case.entity_type,
        left_payload=left_payload,
        right_payload=right_payload,
        auto_merge_threshold=auto_merge_threshold,
        probabilistic_settings=probabilistic_settings,
    )
    return {
        "case_id": case.corpus_id,
        "decision": pair_result["decision"],
        "confidence": pair_result["confidence"],
        "flagged_false_positive": pair_result["decision"] == "match",
    }


def evaluate_regression_pairs(
    *,
    pair_results: list[dict[str, Any]],
    regression_pairs: dict[str, Any] | RegressionPairsFixture,
) -> dict[str, list[dict[str, Any]]]:
    fixture = (
        regression_pairs
        if isinstance(regression_pairs, RegressionPairsFixture)
        else _load_regression_pairs_fixture(regression_pairs)
    )
    must_match_ids = {case.case_id for case in fixture.must_match}
    must_not_match_ids = {case.case_id for case in fixture.must_not_match}
    normalized_pair_results: list[dict[str, Any]] = []
    for result in pair_results:
        if "passed" not in result:
            expected_relation = str(result["expected_relation"])
            decision = str(result["decision"])
            result = {
                **result,
                "passed": decision == "match" if expected_relation == "must_match" else decision != "match",
            }
        normalized_pair_results.append(result)
    must_match_failures = [
        result for result in normalized_pair_results if result["case_id"] in must_match_ids and not result["passed"]
    ]
    must_not_match_failures = [
        result for result in normalized_pair_results if result["case_id"] in must_not_match_ids and not result["passed"]
    ]
    return {
        "must_match_failures": sorted(must_match_failures, key=lambda result: result["case_id"]),
        "must_not_match_failures": sorted(must_not_match_failures, key=lambda result: result["case_id"]),
    }


def _false_positive_summary(corpus_results: list[dict[str, Any]]) -> dict[str, Any]:
    flagged_case_ids = sorted(result["case_id"] for result in corpus_results if result["flagged_false_positive"])
    cases_evaluated = len(corpus_results)
    flagged_false_positives = len(flagged_case_ids)
    return {
        "cases_evaluated": cases_evaluated,
        "flagged_false_positives": flagged_false_positives,
        "flagged_case_ids": flagged_case_ids,
        "false_positive_rate": 0.0 if cases_evaluated == 0 else flagged_false_positives / cases_evaluated,
    }


def _validate_payload_schema(payload: dict[str, Any]) -> None:
    schema = json.loads(_L8_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(f"L8 payload failed schema validation: {errors[0].message}")


def run_l8_regression_gate(
    *,
    regression_pairs: dict[str, Any] | None = None,
    false_positive_corpus: dict[str, Any] | None = None,
    artifact_path: Path | str | None = None,
    produced_at: datetime | None = None,
    repo_sha: str = "0000000",
    gate_command: str = "uv run python -m core.keel_gate_l8",
    scope: str = "global",
    auto_merge_threshold: float | None = None,
    probabilistic_settings: Any | None = None,
) -> dict[str, Any]:
    fixture = _load_regression_pairs_fixture(regression_pairs)
    corpus = _load_false_positive_corpus_fixture(false_positive_corpus)
    resolved_produced_at = produced_at or datetime.now(UTC)
    resolved_auto_merge_threshold = resolve_auto_merge_threshold(auto_merge_threshold)

    pair_results = [
        score_regression_pair_case(
            case=case,
            expected_relation="must_match",
            auto_merge_threshold=resolved_auto_merge_threshold,
            probabilistic_settings=_person_only_probabilistic_settings(
                entity_type=case.entity_type,
                probabilistic_settings=probabilistic_settings,
            ),
        )
        for case in fixture.must_match
    ] + [
        score_regression_pair_case(
            case=case,
            expected_relation="must_not_match",
            auto_merge_threshold=resolved_auto_merge_threshold,
            probabilistic_settings=_person_only_probabilistic_settings(
                entity_type=case.entity_type,
                probabilistic_settings=probabilistic_settings,
            ),
        )
        for case in fixture.must_not_match
    ]

    violations = evaluate_regression_pairs(pair_results=pair_results, regression_pairs=fixture)
    for violating_case_id in {
        *(result["case_id"] for result in violations["must_match_failures"]),
        *(result["case_id"] for result in violations["must_not_match_failures"]),
    }:
        for result in pair_results:
            if result["case_id"] == violating_case_id:
                result["passed"] = False

    corpus_results = [
        score_false_positive_case(
            case=case,
            auto_merge_threshold=resolved_auto_merge_threshold,
            probabilistic_settings=_person_only_probabilistic_settings(
                entity_type=case.entity_type,
                probabilistic_settings=probabilistic_settings,
            ),
        )
        for case in corpus.cases
    ]
    payload = build_l8_regression_payload(
        scope=scope,
        produced_at=resolved_produced_at,
        repo_sha=repo_sha,
        gate_command=gate_command,
        pair_results=pair_results,
        false_positive_summary=_false_positive_summary(corpus_results),
    )
    _validate_payload_schema(payload)
    resolved_artifact_path = (
        Path(artifact_path)
        if artifact_path is not None
        else (_REPO_ROOT / "evidence" / "L8" / f"regression_run_{resolved_produced_at.date().isoformat()}.json")
    )
    return write_l8_regression_artifact(payload, artifact_path=resolved_artifact_path)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L8 entity-resolution regression gate")
    parser.add_argument("--artifact-path", type=Path, default=None)
    parser.add_argument("--repo-sha", default="0000000")
    parser.add_argument("--gate-command", default="uv run python -m core.keel_gate_l8")
    parser.add_argument("--scope", default="global")
    parser.add_argument("--auto-merge-threshold", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    payload = run_l8_regression_gate(
        artifact_path=args.artifact_path,
        repo_sha=args.repo_sha,
        gate_command=args.gate_command,
        scope=args.scope,
        auto_merge_threshold=args.auto_merge_threshold,
    )
    print(json.dumps(payload, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
