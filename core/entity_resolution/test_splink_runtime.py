from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.entity_resolution.splink_runtime import (
    BoundedDuckDBConfig,
    BoundedSplinkLinker,
    build_splink_linker,
    open_bounded_duckdb_connection,
    train_linker,
)


def _bounded_config(tmp_path: Path, **overrides: Any) -> BoundedDuckDBConfig:
    temp_root = tmp_path / "spill"
    temp_root.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "database_path": tmp_path / "benchmark.duckdb",
        "temp_root": temp_root,
        "memory_limit_bytes": 8 * 1024 * 1024,
        "max_temp_directory_size_bytes": 16 * 1024 * 1024,
    }
    values.update(overrides)
    return BoundedDuckDBConfig(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("database_path", Path(":memory:"), "file-backed"),
        ("database_path", Path(""), "file-backed"),
        ("temp_root", Path(".tmp"), "absolute"),
        ("memory_limit_bytes", None, "memory_limit_bytes"),
        ("memory_limit_bytes", 0, "memory_limit_bytes"),
        ("max_temp_directory_size_bytes", None, "max_temp_directory_size_bytes"),
        ("max_temp_directory_size_bytes", 0, "max_temp_directory_size_bytes"),
    ],
)
def test_bounded_duckdb_config_rejects_unbounded_runtime_values(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _bounded_config(tmp_path, **{field: value})


def test_bounded_duckdb_config_rejects_default_dot_tmp_root(tmp_path: Path) -> None:
    default_temp_root = tmp_path / ".tmp"
    default_temp_root.mkdir()

    with pytest.raises(ValueError, match=r"default \.tmp"):
        _bounded_config(tmp_path, temp_root=default_temp_root)


def test_bounded_duckdb_config_rejects_unresolved_temp_root(tmp_path: Path) -> None:
    temp_root = tmp_path / "parent" / ".." / "spill"
    (tmp_path / "spill").mkdir()

    with pytest.raises(ValueError, match="resolved"):
        _bounded_config(tmp_path, temp_root=temp_root)


class _FakeDuckDBConnection:
    def __init__(
        self,
        events: list[str],
        *,
        settings: dict[str, str],
        fail_on_setting: str | None = None,
    ) -> None:
        self.events = events
        self.settings = settings
        self.fail_on_setting = fail_on_setting
        self._next_row: tuple[str] | None = None

    def execute(self, sql: str, parameters: list[str]) -> _FakeDuckDBConnection:
        value = parameters[0]
        if sql.startswith("SET "):
            setting_name = sql.removeprefix("SET ").removesuffix(" = ?")
            self.events.append(f"set:{setting_name}:{value}")
            if setting_name == self.fail_on_setting:
                raise RuntimeError(f"cannot set {setting_name}")
            return self

        assert sql == "SELECT current_setting(?)"
        self.events.append(f"read:{value}")
        self._next_row = (self.settings[value],)
        return self

    def fetchone(self) -> tuple[str] | None:
        return self._next_row

    def close(self) -> None:
        self.events.append("close")


def _fake_connection_opener(
    events: list[str],
    settings: dict[str, str],
    *,
    fail_on_setting: str | None = None,
) -> Any:
    def open_connection(database_path: str) -> _FakeDuckDBConnection:
        events.append(f"connect:{database_path}")
        return _FakeDuckDBConnection(
            events,
            settings=settings,
            fail_on_setting=fail_on_setting,
        )

    return open_connection


def _effective_settings(config: BoundedDuckDBConfig, **overrides: str) -> dict[str, str]:
    settings = {
        "temp_directory": str(config.temp_root),
        "memory_limit": "8.0 MiB",
        "max_temp_directory_size": "16.0 MiB",
    }
    settings.update(overrides)
    return settings


@pytest.mark.parametrize(
    ("setting_name", "effective_value", "message"),
    [
        ("memory_limit", "9.0 MiB", "memory_limit"),
        ("max_temp_directory_size", "17.0 MiB", "max_temp_directory_size"),
    ],
)
def test_bounded_connection_rejects_effective_budget_looser_than_requested(
    tmp_path: Path,
    setting_name: str,
    effective_value: str,
    message: str,
) -> None:
    config = _bounded_config(tmp_path)
    events: list[str] = []
    settings = _effective_settings(config, **{setting_name: effective_value})

    with pytest.raises(RuntimeError, match=message):
        open_bounded_duckdb_connection(
            config,
            connection_opener=_fake_connection_opener(events, settings),
        )

    assert events[-1] == "close"


def test_bounded_connection_rejects_effective_temp_directory_outside_root(
    tmp_path: Path,
) -> None:
    config = _bounded_config(tmp_path)
    events: list[str] = []
    settings = _effective_settings(
        config,
        temp_directory=str(tmp_path / "other_spill"),
    )

    with pytest.raises(RuntimeError, match="outside configured temp root"):
        open_bounded_duckdb_connection(
            config,
            connection_opener=_fake_connection_opener(events, settings),
        )

    assert events[-1] == "close"


def test_bounded_connection_closes_when_setting_application_fails(tmp_path: Path) -> None:
    config = _bounded_config(tmp_path)
    events: list[str] = []

    with pytest.raises(RuntimeError, match="cannot set memory_limit"):
        open_bounded_duckdb_connection(
            config,
            connection_opener=_fake_connection_opener(
                events,
                _effective_settings(config),
                fail_on_setting="memory_limit",
            ),
        )

    assert events[-1] == "close"


def test_bounded_linker_uses_one_preflighted_connection_before_registration(
    tmp_path: Path,
) -> None:
    config = _bounded_config(tmp_path)
    events: list[str] = []
    connections: list[_FakeDuckDBConnection] = []
    db_apis: list[object] = []

    def open_connection(database_path: str) -> _FakeDuckDBConnection:
        events.append(f"connect:{database_path}")
        connection = _FakeDuckDBConnection(
            events,
            settings=_effective_settings(config),
        )
        connections.append(connection)
        return connection

    def bounded_connection_factory() -> _FakeDuckDBConnection:
        return open_bounded_duckdb_connection(
            config,
            connection_opener=open_connection,
        )

    class FakeDuckDBAPI:
        def __init__(self, *, connection: object) -> None:
            events.append("duckdb_api")
            assert connection is connections[0]
            self.connection = connection
            db_apis.append(self)

        def register_table(
            self,
            input_rows: object,
            table_name: str,
            overwrite: bool = False,
        ) -> None:
            events.append("register_table")
            assert table_name == "__splink_input_rows"
            assert overwrite is True

    class FakeLinker:
        def __init__(self, input_table: str, settings: object, db_api: object) -> None:
            events.append("linker")
            assert input_table == "__splink_input_rows"
            assert db_api is db_apis[0]

    session = build_splink_linker(
        [{"id": "one", "canonical_name": "One"}],
        object(),
        runtime_resolver=lambda: (FakeLinker, FakeDuckDBAPI),
        bounded_connection_factory=bounded_connection_factory,
    )

    assert isinstance(session, BoundedSplinkLinker)
    assert len(connections) == 1
    assert session.linker.__class__ is FakeLinker
    assert events == [
        f"connect:{config.database_path}",
        f"set:temp_directory:{config.temp_root}",
        f"set:memory_limit:{config.memory_limit_bytes}B",
        f"set:max_temp_directory_size:{config.max_temp_directory_size_bytes}B",
        "read:temp_directory",
        "read:memory_limit",
        "read:max_temp_directory_size",
        "duckdb_api",
        "register_table",
        "linker",
    ]

    session.close()
    assert events[-1] == "close"


def test_train_linker_tries_next_rule_when_first_has_no_pairs() -> None:
    class FakeTraining:
        def __init__(self) -> None:
            self.u_calls: list[int] = []
            self.em_calls: list[object] = []

        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            self.u_calls.append(max_pairs)

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: object,
        ) -> None:
            self.em_calls.append(blocking_rule)
            if blocking_rule == "rule_a":
                raise RuntimeError("Training rule `rule_a` resulted in no record pairs.")

    class FakeLinker:
        def __init__(self) -> None:
            self.training = FakeTraining()

    linker = FakeLinker()
    train_linker(linker, ["rule_a", "rule_b"])

    assert linker.training.u_calls == [1_000_000]
    assert linker.training.em_calls == ["rule_a", "rule_b"]


def test_train_linker_raises_for_non_no_pair_training_errors() -> None:
    class FakeTraining:
        def estimate_u_using_random_sampling(self, *, max_pairs: int) -> None:
            assert max_pairs == 1_000_000

        def estimate_parameters_using_expectation_maximisation(
            self,
            blocking_rule: object,
        ) -> None:
            raise RuntimeError("unexpected training failure")

    class FakeLinker:
        def __init__(self) -> None:
            self.training = FakeTraining()

    with pytest.raises(RuntimeError, match="unexpected training failure"):
        train_linker(FakeLinker(), ["rule_a"])
