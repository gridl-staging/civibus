from __future__ import annotations

from uuid import uuid4

import pytest

from core.entity_resolution.blocking import (
    count_blocked_pairs,
    describe_blocking_rules,
)
from core.entity_resolution.extract import RowDict


class _FakeBlockingRule:
    def __init__(self, rule_sql: str) -> None:
        self.blocking_rule_sql = rule_sql


class _FakeSettings:
    def __init__(self, rules: list[object]) -> None:
        self.blocking_rules_to_generate_predictions = rules


class _FakeSplink4RuleCreator:
    """Simulates a Splink 4 BlockingRuleCreator (no blocking_rule_sql attr)."""

    def __init__(self, sql: str) -> None:
        self._sql = sql

    def get_blocking_rule(self, dialect: str) -> _FakeBlockingRule:
        return _FakeBlockingRule(self._sql)


def test_describe_blocking_rules_resolves_splink4_rule_creators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splink 4 rule objects without blocking_rule_sql are resolved via get_blocking_rule()."""
    expected_settings = _FakeSettings([_FakeSplink4RuleCreator("l.last_name = r.last_name")])
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: expected_settings if entity_type == "person" else None,
    )

    rules = describe_blocking_rules("person")

    assert rules == [
        {"rule_index": 0, "blocking_rule": "l.last_name = r.last_name"},
    ]


def test_describe_blocking_rules_returns_rule_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule metadata should come from the Splink settings object."""
    expected_settings = _FakeSettings(
        [
            _FakeBlockingRule("l.last_name = r.last_name"),
            _FakeBlockingRule("l.zip5 = r.zip5"),
        ]
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: expected_settings if entity_type == "person" else None,
    )

    rules = describe_blocking_rules("person")

    assert rules == [
        {"rule_index": 0, "blocking_rule": "l.last_name = r.last_name"},
        {"rule_index": 1, "blocking_rule": "l.zip5 = r.zip5"},
    ]


def test_count_blocked_pairs_raises_when_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime dependency errors are raised even when settings are present."""
    rows: list[RowDict] = [{"id": uuid4(), "canonical_name": "No Runtime"}]
    person_settings = _FakeSettings([_FakeBlockingRule("l.last_name = r.last_name")])

    def _raise_runtime_error() -> tuple[object, object]:
        raise RuntimeError("Splink runtime is required for probabilistic scoring.")

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: person_settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        _raise_runtime_error,
    )

    with pytest.raises(RuntimeError, match="Splink"):
        count_blocked_pairs(rows, "person")


def test_count_blocked_pairs_uses_predict_and_counts_by_match_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-rule counts are derived from Splink prediction output match_key values."""
    rows: list[RowDict] = [
        {"id": uuid4(), "canonical_name": "One"},
        {"id": uuid4(), "canonical_name": "Two"},
    ]
    settings = _FakeSettings(
        [
            _FakeBlockingRule("rule_0_sql"),
            _FakeBlockingRule("rule_1_sql"),
        ]
    )
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        def __init__(self) -> None:
            runtime_calls["duckdb_created"] = True

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "match_key": "0",
                    "unique_id_l": str(rows[0]["id"]),
                    "unique_id_r": str(rows[1]["id"]),
                },
                {
                    "match_key": "0",
                    "unique_id_l": str(rows[1]["id"]),
                    "unique_id_r": str(rows[0]["id"]),
                },
                {
                    "match_key": "1",
                    "unique_id_l": str(rows[0]["id"]),
                    "unique_id_r": str(rows[1]["id"]),
                },
            ]

    class FakeInference:
        def predict(self) -> FakePredictions:
            runtime_calls["predict_called"] = True
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], in_settings: object, db_api: object) -> None:
            runtime_calls["rows"] = input_rows
            runtime_calls["settings"] = in_settings
            runtime_calls["db_api"] = db_api
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "organization" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    counts = count_blocked_pairs(rows, "organization")

    assert runtime_calls["duckdb_created"] is True
    assert runtime_calls["rows"] == [
        {"id": str(rows[0]["id"]), "canonical_name": "One"},
        {"id": str(rows[1]["id"]), "canonical_name": "Two"},
    ]
    assert runtime_calls["settings"] is settings
    assert runtime_calls["predict_called"] is True
    assert counts == [
        {"rule_index": 0, "blocking_rule": "rule_0_sql", "pair_count": 2},
        {"rule_index": 1, "blocking_rule": "rule_1_sql", "pair_count": 1},
    ]


def test_count_blocked_pairs_prepares_duplicate_entity_rows_with_unique_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_id = uuid4()
    other_id = uuid4()
    rows: list[RowDict] = [
        {"id": shared_id, "canonical_name": "One", "identifier_key": "fec_id:FEC-123"},
        {"id": shared_id, "canonical_name": "One", "identifier_key": "voter_reg_id:VR-123"},
        {"id": other_id, "canonical_name": "Two", "identifier_key": None},
    ]
    settings = _FakeSettings([_FakeBlockingRule("rule_0_sql")])
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return []

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], in_settings: object, db_api: object) -> None:
            runtime_calls["rows"] = input_rows
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    count_blocked_pairs(rows, "person")

    assert runtime_calls["rows"] == [
        {
            "id": f"{shared_id}__splink_row__0",
            "canonical_name": "One",
            "identifier_key": "fec_id:FEC-123",
        },
        {
            "id": f"{shared_id}__splink_row__1",
            "canonical_name": "One",
            "identifier_key": "voter_reg_id:VR-123",
        },
        {"id": str(other_id), "canonical_name": "Two", "identifier_key": None},
    ]


def test_count_blocked_pairs_ignores_same_entity_synthetic_row_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_id = uuid4()
    other_id = uuid4()
    rows: list[RowDict] = [
        {"id": shared_id, "canonical_name": "One", "identifier_key": "fec_id:FEC-123"},
        {"id": shared_id, "canonical_name": "One", "identifier_key": "voter_reg_id:VR-123"},
        {"id": other_id, "canonical_name": "Two", "identifier_key": None},
    ]
    settings = _FakeSettings([_FakeBlockingRule("rule_0_sql"), _FakeBlockingRule("rule_1_sql")])

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "match_key": "0",
                    "unique_id_l": f"{shared_id}__splink_row__0",
                    "unique_id_r": f"{shared_id}__splink_row__1",
                },
                {
                    "match_key": "1",
                    "unique_id_l": f"{shared_id}__splink_row__1",
                    "unique_id_r": str(other_id),
                },
            ]

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], in_settings: object, db_api: object) -> None:
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    counts = count_blocked_pairs(rows, "person")

    assert counts == [
        {"rule_index": 0, "blocking_rule": "rule_0_sql", "pair_count": 0},
        {"rule_index": 1, "blocking_rule": "rule_1_sql", "pair_count": 1},
    ]
