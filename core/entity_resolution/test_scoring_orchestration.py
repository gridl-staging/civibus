from __future__ import annotations

from uuid import uuid4

import pytest

from core.entity_resolution.extract import RowDict
from core.entity_resolution.scoring import score_entities


def test_score_entities_runs_deterministic_then_probabilistic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator runs deterministic first, then Splink over unresolved rows, then combines."""
    person_a = uuid4()
    person_b = uuid4()
    person_c = uuid4()
    ordered_pair = (min(person_a, person_b), max(person_a, person_b))
    call_order: list[str] = []

    rows: list[RowDict] = [
        {"id": person_a, "canonical_name": "A"},
        {"id": person_b, "canonical_name": "B"},
        {"id": person_c, "canonical_name": "C"},
    ]
    deterministic_pairs = [
        {
            "entity_id_a": ordered_pair[0],
            "entity_id_b": ordered_pair[1],
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        }
    ]
    probabilistic_pairs = [
        {
            "entity_id_a": person_c,
            "entity_id_b": person_c,
            "confidence": 0.72,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]

    def _fake_extract_rows_for_matching(conn: object, entity_type: str) -> list[RowDict]:
        assert entity_type == "person"
        call_order.append("extract")
        return rows

    def _fake_run_deterministic_rules(conn: object, entity_type: str) -> list[dict]:
        assert entity_type == "person"
        call_order.append("deterministic")
        return deterministic_pairs

    def _fake_score_with_splink(unresolved: list[RowDict], entity_type: str) -> list[dict]:
        assert entity_type == "person"
        call_order.append("probabilistic")
        assert [row["id"] for row in unresolved] == [person_c]
        return probabilistic_pairs

    monkeypatch.setattr(
        "core.entity_resolution.scoring.extract_rows_for_matching",
        _fake_extract_rows_for_matching,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.run_deterministic_rules",
        _fake_run_deterministic_rules,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.score_with_splink",
        _fake_score_with_splink,
    )

    combined = score_entities(object(), "person")

    assert call_order == ["extract", "deterministic", "probabilistic"]
    assert combined == deterministic_pairs + probabilistic_pairs


def test_score_entities_skips_probabilistic_when_all_rows_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splink is skipped when deterministic matches resolve every extracted row."""
    person_a = uuid4()
    person_b = uuid4()
    rows: list[RowDict] = [
        {"id": person_a, "canonical_name": "A"},
        {"id": person_b, "canonical_name": "B"},
    ]
    deterministic_pairs = [
        {
            "entity_id_a": min(person_a, person_b),
            "entity_id_b": max(person_a, person_b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        }
    ]
    score_called = False

    monkeypatch.setattr(
        "core.entity_resolution.scoring.extract_rows_for_matching",
        lambda conn, entity_type: rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.run_deterministic_rules",
        lambda conn, entity_type: deterministic_pairs,
    )

    def _should_not_run(_: list[RowDict], __: str) -> list[dict]:
        nonlocal score_called
        score_called = True
        return []

    monkeypatch.setattr("core.entity_resolution.scoring.score_with_splink", _should_not_run)

    result = score_entities(object(), "person")

    assert result == deterministic_pairs
    assert score_called is False


def test_score_entities_threads_explicit_probabilistic_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_a = uuid4()
    rows: list[RowDict] = [{"id": person_a, "canonical_name": "A"}]
    candidate_settings = {"candidate": "stage3"}
    captured_settings: list[object] = []

    monkeypatch.setattr(
        "core.entity_resolution.scoring.extract_rows_for_matching",
        lambda conn, entity_type: rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.run_deterministic_rules",
        lambda conn, entity_type: [],
    )

    def _fake_score_with_splink(
        unresolved: list[RowDict],
        entity_type: str,
        *,
        probabilistic_settings: object | None = None,
    ) -> list[dict]:
        assert unresolved == rows
        assert entity_type == "person"
        captured_settings.append(probabilistic_settings)
        return []

    monkeypatch.setattr("core.entity_resolution.scoring.score_with_splink", _fake_score_with_splink)

    score_entities(
        object(),
        "person",
        probabilistic_settings=candidate_settings,
    )

    assert captured_settings == [candidate_settings]
