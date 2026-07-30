from __future__ import annotations

from uuid import uuid4

import pytest

from core.entity_resolution.blocking import (
    count_blocked_pairs,
    describe_blocking_rules,
    fired_blocking_rules_for_pair,
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


def test_fired_blocking_rules_for_pair_returns_every_true_rule() -> None:
    rules = [
        {
            "rule_index": 0,
            "blocking_rule": 'l."last_name" = r."last_name" AND l."state" = r."state"',
        },
        {
            "rule_index": 1,
            "blocking_rule": 'l."zip5" = r."zip5" AND l."last_name_prefix5" = r."last_name_prefix5"',
        },
        {
            "rule_index": 2,
            "blocking_rule": 'l."street_number" = r."street_number"',
        },
    ]
    left = {
        "last_name": "DOE",
        "state": "NC",
        "zip5": "27601",
        "last_name_prefix5": "DOE",
        "street_number": None,
    }
    right = dict(left)

    assert fired_blocking_rules_for_pair(left, right, rules) == [
        {"match_key": "0", "blocking_rule": rules[0]["blocking_rule"]},
        {"match_key": "1", "blocking_rule": rules[1]["blocking_rule"]},
    ]


def test_fired_blocking_rules_for_pair_fails_closed_on_unsupported_sql() -> None:
    with pytest.raises(ValueError, match="unsupported blocking-rule expression"):
        fired_blocking_rules_for_pair(
            {"last_name": "DOE"},
            {"last_name": "DOE"},
            [
                {
                    "rule_index": 0,
                    "blocking_rule": 'levenshtein(l."last_name", r."last_name") <= 1',
                }
            ],
        )


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


def test_count_blocked_pairs_empty_rows_still_enforce_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty inputs must still prove the blocking-analysis runtime boundary."""
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
        count_blocked_pairs([], "person")


def test_count_blocked_pairs_raises_when_blocking_analysis_apis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[RowDict] = [{"id": uuid4(), "canonical_name": "No Blocking Analysis"}]
    person_settings = _FakeSettings([_FakeBlockingRule("l.last_name = r.last_name")])

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: person_settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.cumulative_comparisons_to_be_scored_from_blocking_rules_data",
        None,
    )
    monkeypatch.setattr("core.entity_resolution.blocking.n_largest_blocks", None)

    with pytest.raises(RuntimeError, match="Splink blocking-analysis APIs are required"):
        count_blocked_pairs(rows, "person")


def _patch_blocking_analysis(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[object],
    cumulative_records: list[dict[str, object]],
    largest_records_by_rule: dict[str, list[dict[str, object]]] | None = None,
) -> None:
    largest_records = largest_records_by_rule or {}

    monkeypatch.setattr(
        "core.entity_resolution.blocking.cumulative_comparisons_to_be_scored_from_blocking_rules_data",
        lambda **kwargs: calls.append(("cumulative", kwargs)) or cumulative_records,
        raising=False,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.n_largest_blocks",
        lambda **kwargs: calls.append(("largest", kwargs)) or largest_records.get(str(kwargs["blocking_rule"]), []),
        raising=False,
    )


def test_count_blocked_pairs_uses_public_blocking_analysis_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[object] = []

    class FakeDuckDBAPI:
        def __init__(self) -> None:
            calls.append("duckdb_created")

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "organization" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(
        monkeypatch,
        calls,
        [
            {"match_key": "0", "row_count": 2, "cumulative_rows": 2},
            {"match_key": "1", "row_count": 1, "cumulative_rows": 3},
        ],
        {
            "rule_0_sql": [{"block_count": 2}],
            "rule_1_sql": [{"block_count": 1}],
        },
    )

    counts = count_blocked_pairs(rows, "organization")

    assert calls[0] == "duckdb_created"
    assert calls[1][0] == "cumulative"
    assert calls[1][1]["table_or_tables"] == [
        [
            {"id": str(rows[0]["id"]), "canonical_name": "One"},
            {"id": str(rows[1]["id"]), "canonical_name": "Two"},
        ]
    ]
    assert calls[1][1]["blocking_rules"] == ["rule_0_sql", "rule_1_sql"]
    assert counts == [
        {
            "rule_index": 0,
            "blocking_rule": "rule_0_sql",
            "exclusive_pair_count": 2,
            "cumulative_pair_count": 2,
            "max_block_size": 2,
        },
        {
            "rule_index": 1,
            "blocking_rule": "rule_1_sql",
            "exclusive_pair_count": 1,
            "cumulative_pair_count": 3,
            "max_block_size": 1,
        },
    ]


def test_count_blocked_pairs_uses_public_blocking_analysis_without_predict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    calls: list[object] = []

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(
        monkeypatch,
        calls,
        [
            {"match_key": "0", "row_count": 3, "cumulative_rows": 3},
            {"match_key": "1", "row_count": 1, "cumulative_rows": 4},
        ],
        {"rule_1_sql": [{"block_count": 4}]},
    )

    counts = count_blocked_pairs(rows, "person")

    assert calls[0][0] == "cumulative"
    assert calls[0][1]["table_or_tables"] == [
        [
            {"id": str(rows[0]["id"]), "canonical_name": "One"},
            {"id": str(rows[1]["id"]), "canonical_name": "Two"},
        ]
    ]
    assert calls[0][1]["blocking_rules"] == ["rule_0_sql", "rule_1_sql"]
    assert calls[0][1]["link_type"] == "dedupe_only"
    assert calls[0][1]["unique_id_column_name"] == "id"
    assert calls[2][0] == "largest"
    assert calls[2][1]["blocking_rule"] == "rule_1_sql"
    assert calls[2][1]["n_largest"] == 1
    assert counts == [
        {
            "rule_index": 0,
            "blocking_rule": "rule_0_sql",
            "exclusive_pair_count": 3,
            "cumulative_pair_count": 3,
            "max_block_size": 0,
        },
        {
            "rule_index": 1,
            "blocking_rule": "rule_1_sql",
            "exclusive_pair_count": 1,
            "cumulative_pair_count": 4,
            "max_block_size": 4,
        },
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
    calls: list[object] = []

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(monkeypatch, calls, [{"match_key": "0", "row_count": 0, "cumulative_rows": 0}])

    count_blocked_pairs(rows, "person")

    assert calls[0][1]["table_or_tables"] == [
        [
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
    ]


def test_count_blocked_pairs_returns_exclusive_counts_from_cumulative_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[RowDict] = [
        {"id": uuid4(), "canonical_name": "One"},
        {"id": uuid4(), "canonical_name": "Two"},
    ]
    settings = _FakeSettings([_FakeBlockingRule("rule_0_sql"), _FakeBlockingRule("rule_1_sql")])
    calls: list[object] = []

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(
        monkeypatch,
        calls,
        [
            {"match_key": "0", "row_count": 0, "cumulative_rows": 0},
            {"match_key": "1", "row_count": 1, "cumulative_rows": 1},
        ],
    )

    counts = count_blocked_pairs(rows, "person")

    assert counts == [
        {
            "rule_index": 0,
            "blocking_rule": "rule_0_sql",
            "exclusive_pair_count": 0,
            "cumulative_pair_count": 0,
            "max_block_size": 0,
        },
        {
            "rule_index": 1,
            "blocking_rule": "rule_1_sql",
            "exclusive_pair_count": 1,
            "cumulative_pair_count": 1,
            "max_block_size": 0,
        },
    ]


@pytest.mark.parametrize(
    ("cumulative_record", "missing_field"),
    [
        ({"row_count": 1, "cumulative_rows": 1}, "rule index"),
        ({"match_key": "0", "row_count": 1}, "cumulative pair count"),
    ],
)
def test_count_blocked_pairs_rejects_unrecognized_cumulative_record_shape(
    monkeypatch: pytest.MonkeyPatch,
    cumulative_record: dict[str, object],
    missing_field: str,
) -> None:
    rows: list[RowDict] = [
        {"id": uuid4(), "canonical_name": "One"},
        {"id": uuid4(), "canonical_name": "Two"},
    ]
    settings = _FakeSettings([_FakeBlockingRule("rule_0_sql")])

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(monkeypatch, [], [cumulative_record])

    with pytest.raises(RuntimeError, match=missing_field):
        count_blocked_pairs(rows, "person")


def test_count_blocked_pairs_rejects_unrecognized_largest_block_record_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[RowDict] = [
        {"id": uuid4(), "canonical_name": "One"},
        {"id": uuid4(), "canonical_name": "Two"},
    ]
    settings = _FakeSettings([_FakeBlockingRule("rule_0_sql")])

    class FakeDuckDBAPI:
        pass

    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_probabilistic_settings",
        lambda entity_type: settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.blocking.get_splink_runtime",
        lambda: (object, FakeDuckDBAPI),
    )
    _patch_blocking_analysis(
        monkeypatch,
        [],
        [{"match_key": "0", "row_count": 1, "cumulative_rows": 1}],
        {"rule_0_sql": [{"unexpected_count": 4}]},
    )

    with pytest.raises(RuntimeError, match="maximum block size"):
        count_blocked_pairs(rows, "person")
