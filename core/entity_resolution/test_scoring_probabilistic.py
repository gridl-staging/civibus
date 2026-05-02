from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest

from core.entity_resolution.extract import RowDict
from core.entity_resolution.scoring import score_with_splink


def _require_pandas_dataframe_runtime() -> None:
    if not hasattr(pd, "DataFrame"):
        pytest.skip("Pandas DataFrame runtime unavailable; install the entity-resolution extra for full coverage.")


def test_score_with_splink_raises_when_splink_runtime_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime dependency errors are raised even when settings are present."""
    rows: list[RowDict] = [{"id": uuid4(), "canonical_name": "No Runtime"}]
    person_settings = object()

    def _raise_runtime_error() -> tuple[object, object]:
        raise RuntimeError("Splink runtime is required for probabilistic scoring.")

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: person_settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        _raise_runtime_error,
    )

    with pytest.raises(RuntimeError, match="Splink"):
        score_with_splink(rows, "person")


def test_score_with_splink_empty_rows_still_enforce_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty inputs still validate the required probabilistic runtime."""
    person_settings = object()

    def _raise_runtime_error() -> tuple[object, object]:
        raise RuntimeError("Splink runtime is required for probabilistic scoring.")

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: person_settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        _raise_runtime_error,
    )

    with pytest.raises(RuntimeError, match="Splink"):
        score_with_splink([], "person")


def test_score_with_splink_runs_training_and_maps_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When runtime is available, Linker is trained and predictions map to scored-pair contract."""
    left_id = uuid4()
    right_id = uuid4()
    rows: list[RowDict] = [
        {"id": left_id, "canonical_name": "Alpha"},
        {"id": right_id, "canonical_name": "Beta"},
    ]

    person_settings = object()
    expected_rule = "l.last_name = r.last_name"
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        def __init__(self) -> None:
            runtime_calls["duckdb_created"] = True

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "unique_id_l": str(left_id),
                    "unique_id_r": str(right_id),
                    "match_probability": 0.91,
                }
            ]

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            runtime_calls["u_max_pairs"] = max_pairs

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: str,
        ) -> None:
            runtime_calls["em_rule"] = blocking_rule

    class FakeInference:
        def predict(self) -> FakePredictions:
            runtime_calls["predict_called"] = True
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], settings: object, db_api: object) -> None:
            runtime_calls["rows"] = input_rows
            runtime_calls["settings"] = settings
            runtime_calls["db_api"] = db_api
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: person_settings if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type: [expected_rule] if entity_type == "person" else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    results = score_with_splink(rows, "person")

    assert runtime_calls["duckdb_created"] is True
    assert runtime_calls["rows"] == [
        {"id": str(left_id), "canonical_name": "Alpha"},
        {"id": str(right_id), "canonical_name": "Beta"},
    ]
    assert runtime_calls["settings"] is person_settings
    assert runtime_calls["u_max_pairs"] == 1_000_000
    assert runtime_calls["em_rule"] == expected_rule
    assert runtime_calls["predict_called"] is True
    assert results == [
        {
            "entity_id_a": min(left_id, right_id),
            "entity_id_b": max(left_id, right_id),
            "confidence": 0.91,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]


def test_score_with_splink_registers_rows_before_linker_init_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_pandas_dataframe_runtime()
    left_id = uuid4()
    right_id = uuid4()
    rows: list[RowDict] = [
        {"id": left_id, "canonical_name": "Alpha"},
        {"id": right_id, "canonical_name": "Beta"},
    ]
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        def register_table(
            self,
            input_rows: list[RowDict],
            table_name: str,
            overwrite: bool = False,
        ) -> None:
            runtime_calls["register_rows"] = input_rows
            runtime_calls["register_table_name"] = table_name
            runtime_calls["register_overwrite"] = overwrite

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "unique_id_l": str(left_id),
                    "unique_id_r": str(right_id),
                    "match_probability": 0.88,
                }
            ]

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            runtime_calls["u_max_pairs"] = max_pairs

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: str,
        ) -> None:
            runtime_calls["em_rule"] = blocking_rule

    class FakeInference:
        def predict(self) -> FakePredictions:
            runtime_calls["predict_called"] = True
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_table: str, settings: object, db_api: object) -> None:
            runtime_calls["input_table"] = input_table
            runtime_calls["settings"] = settings
            runtime_calls["db_api"] = db_api
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: object() if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type: ["l.last_name = r.last_name"] if entity_type == "person" else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    result = score_with_splink(rows, "person")

    registered_rows = runtime_calls["register_rows"]
    assert isinstance(registered_rows, pd.DataFrame)
    assert registered_rows.to_dict(orient="records") == [
        {"id": str(left_id), "canonical_name": "Alpha"},
        {"id": str(right_id), "canonical_name": "Beta"},
    ]
    assert runtime_calls["register_table_name"] == "__splink_input_rows"
    assert runtime_calls["register_overwrite"] is True
    assert runtime_calls["input_table"] == "__splink_input_rows"
    assert runtime_calls["u_max_pairs"] == 1_000_000
    assert runtime_calls["em_rule"] == "l.last_name = r.last_name"
    assert runtime_calls["predict_called"] is True
    assert result == [
        {
            "entity_id_a": min(left_id, right_id),
            "entity_id_b": max(left_id, right_id),
            "confidence": 0.88,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]


def _capture_registered_input_frame(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[RowDict],
    entity_type: str,
    blocking_rule: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    _require_pandas_dataframe_runtime()
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        def register_table(
            self,
            input_rows: object,
            table_name: str,
            overwrite: bool = False,
        ) -> None:
            runtime_calls["register_rows"] = input_rows
            runtime_calls["register_table_name"] = table_name
            runtime_calls["register_overwrite"] = overwrite

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return []

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            runtime_calls["u_max_pairs"] = max_pairs

        def estimate_parameters_using_expectation_maximisation(
            self,
            rule_sql: str,
        ) -> None:
            runtime_calls["em_rule"] = rule_sql

    class FakeInference:
        def predict(self) -> FakePredictions:
            runtime_calls["predict_called"] = True
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_table: str, settings: object, db_api: object) -> None:
            runtime_calls["input_table"] = input_table
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda current_entity_type: object() if current_entity_type == entity_type else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda current_entity_type: [blocking_rule] if current_entity_type == entity_type else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    score_with_splink(rows, entity_type)

    registered = runtime_calls["register_rows"]
    assert isinstance(registered, pd.DataFrame)
    assert runtime_calls["register_table_name"] == "__splink_input_rows"
    assert runtime_calls["register_overwrite"] is True
    assert runtime_calls["input_table"] == "__splink_input_rows"
    assert runtime_calls["u_max_pairs"] == 1_000_000
    assert runtime_calls["em_rule"] == blocking_rule
    assert runtime_calls["predict_called"] is True
    return registered, runtime_calls


@pytest.mark.parametrize(
    ("entity_type", "blocking_rule", "string_null_columns", "datetime_null_columns"),
    [
        (
            "person",
            "l.last_name = r.last_name",
            ("normalized_address", "zip5", "state", "employer", "occupation"),
            ("date_of_birth",),
        ),
        (
            "organization",
            'l."ein" = r."ein"',
            (
                "canonical_name_soundex",
                "name_prefix5",
                "ein",
                "fec_committee_id",
                "registered_agent_name",
            ),
            (),
        ),
    ],
)
def test_score_with_splink_registers_typed_null_columns(
    monkeypatch: pytest.MonkeyPatch,
    entity_type: str,
    blocking_rule: str,
    string_null_columns: tuple[str, ...],
    datetime_null_columns: tuple[str, ...],
) -> None:
    left_id = uuid4()
    right_id = uuid4()
    if entity_type == "person":
        rows: list[RowDict] = [
            {
                "id": left_id,
                "canonical_name": "Alpha",
                "first_name": "Alpha",
                "last_name": "One",
                "normalized_address": None,
                "date_of_birth": None,
                "zip5": None,
                "state": None,
                "employer": None,
                "occupation": None,
            },
            {
                "id": right_id,
                "canonical_name": "Beta",
                "first_name": "Beta",
                "last_name": "Two",
                "normalized_address": None,
                "date_of_birth": None,
                "zip5": None,
                "state": None,
                "employer": None,
                "occupation": None,
            },
        ]
    else:
        rows = [
            {
                "id": left_id,
                "canonical_name": "Alpha Org",
                "canonical_name_soundex": None,
                "name_prefix5": None,
                "registered_state": None,
                "normalized_address": None,
                "zip5": None,
                "org_type": None,
                "ein": None,
                "fec_committee_id": None,
                "registered_agent_name": None,
            },
            {
                "id": right_id,
                "canonical_name": "Beta Org",
                "canonical_name_soundex": None,
                "name_prefix5": None,
                "registered_state": None,
                "normalized_address": None,
                "zip5": None,
                "org_type": None,
                "ein": None,
                "fec_committee_id": None,
                "registered_agent_name": None,
            },
        ]

    registered, _runtime_calls = _capture_registered_input_frame(
        monkeypatch,
        rows=rows,
        entity_type=entity_type,
        blocking_rule=blocking_rule,
    )

    for column_name in string_null_columns:
        assert str(registered[column_name].dtype).startswith("string")
    for column_name in datetime_null_columns:
        assert str(registered[column_name].dtype).startswith("datetime64")


def test_score_with_splink_prepares_duplicate_entity_rows_with_unique_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate entity rows keep their blocking keys while gaining unique Splink IDs."""
    shared_id = uuid4()
    other_id = uuid4()
    rows: list[RowDict] = [
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "fec_id:FEC-123"},
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "voter_reg_id:VR-123"},
        {"id": other_id, "canonical_name": "Beta", "identifier_key": None},
    ]
    runtime_calls: dict[str, object] = {}

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return []

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            runtime_calls["u_max_pairs"] = max_pairs

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: str,
        ) -> None:
            runtime_calls["em_rule"] = blocking_rule

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], settings: object, db_api: object) -> None:
            runtime_calls["rows"] = input_rows
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: object() if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type: ["l.last_name = r.last_name"] if entity_type == "person" else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    score_with_splink(rows, "person")

    assert runtime_calls["rows"] == [
        {
            "id": f"{shared_id}__splink_row__0",
            "canonical_name": "Alpha",
            "identifier_key": "fec_id:FEC-123",
        },
        {
            "id": f"{shared_id}__splink_row__1",
            "canonical_name": "Alpha",
            "identifier_key": "voter_reg_id:VR-123",
        },
        {"id": str(other_id), "canonical_name": "Beta", "identifier_key": None},
    ]


def test_score_with_splink_maps_synthetic_row_ids_back_to_entity_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_id = uuid4()
    other_id = uuid4()
    rows: list[RowDict] = [
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "fec_id:FEC-123"},
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "voter_reg_id:VR-123"},
        {"id": other_id, "canonical_name": "Beta", "identifier_key": None},
    ]

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "unique_id_l": f"{shared_id}__splink_row__1",
                    "unique_id_r": str(other_id),
                    "match_probability": 0.87,
                }
            ]

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            assert max_pairs == 1_000_000

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: str,
        ) -> None:
            assert blocking_rule == "l.last_name = r.last_name"

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], settings: object, db_api: object) -> None:
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: object() if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type: ["l.last_name = r.last_name"] if entity_type == "person" else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    results = score_with_splink(rows, "person")

    assert results == [
        {
            "entity_id_a": min(shared_id, other_id),
            "entity_id_b": max(shared_id, other_id),
            "confidence": 0.87,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]


def test_score_with_splink_ignores_same_entity_synthetic_row_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_id = uuid4()
    other_id = uuid4()
    rows: list[RowDict] = [
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "fec_id:FEC-123"},
        {"id": shared_id, "canonical_name": "Alpha", "identifier_key": "voter_reg_id:VR-123"},
        {"id": other_id, "canonical_name": "Beta", "identifier_key": None},
    ]

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "unique_id_l": f"{shared_id}__splink_row__0",
                    "unique_id_r": f"{shared_id}__splink_row__1",
                    "match_probability": 0.99,
                },
                {
                    "unique_id_l": f"{shared_id}__splink_row__1",
                    "unique_id_r": str(other_id),
                    "match_probability": 0.87,
                },
            ]

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            assert max_pairs == 1_000_000

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: str,
        ) -> None:
            assert blocking_rule == "l.last_name = r.last_name"

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], settings: object, db_api: object) -> None:
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: object() if entity_type == "person" else None,
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type: ["l.last_name = r.last_name"] if entity_type == "person" else [],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    results = score_with_splink(rows, "person")

    assert results == [
        {
            "entity_id_a": min(shared_id, other_id),
            "entity_id_b": max(shared_id, other_id),
            "confidence": 0.87,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]


def test_score_with_splink_uses_explicit_candidate_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left_id = uuid4()
    right_id = uuid4()
    rows: list[RowDict] = [
        {"id": left_id, "canonical_name": "Alpha"},
        {"id": right_id, "canonical_name": "Beta"},
    ]
    candidate_settings = {"blocking_rules_to_generate_predictions": ["x"]}

    class FakeDuckDBAPI:
        pass

    class FakePredictions:
        def as_record_dict(self) -> list[dict[str, object]]:
            return [
                {
                    "unique_id_l": str(left_id),
                    "unique_id_r": str(right_id),
                    "match_probability": 0.88,
                }
            ]

    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            assert max_pairs == 1_000_000

        def estimate_parameters_using_expectation_maximisation(self, blocking_rule: str) -> None:
            assert blocking_rule == "l.last_name = r.last_name"

    class FakeInference:
        def predict(self) -> FakePredictions:
            return FakePredictions()

    class FakeLinker:
        def __init__(self, input_rows: list[RowDict], settings: object, db_api: object) -> None:
            assert settings is candidate_settings
            self.training = FakeTraining()
            self.inference = FakeInference()

    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_probabilistic_settings",
        lambda entity_type: pytest.fail("global settings lookup should be bypassed"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_blocking_rule_sqls",
        lambda entity_type, probabilistic_settings=None: ["l.last_name = r.last_name"],
    )
    monkeypatch.setattr(
        "core.entity_resolution.scoring.get_splink_runtime",
        lambda: (FakeLinker, FakeDuckDBAPI),
    )

    results = score_with_splink(rows, "person", probabilistic_settings=candidate_settings)

    assert results == [
        {
            "entity_id_a": min(left_id, right_id),
            "entity_id_b": max(left_id, right_id),
            "confidence": 0.88,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
