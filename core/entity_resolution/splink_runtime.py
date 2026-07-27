from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_DATETIME_COLUMNS = {"date_of_birth"}
_DUCKDB_SIZE_UNITS = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
}
_DUCKDB_SIZE_PATTERN = re.compile(r"^(?P<amount>\d+(?:\.\d+)?) (?P<unit>[KMGT]iB|B)$")
BoundedConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class BoundedDuckDBConfig:
    """Validated file and resource boundaries for one DuckDB scoring run."""

    database_path: Path
    temp_root: Path
    memory_limit_bytes: int
    max_temp_directory_size_bytes: int

    def __post_init__(self) -> None:
        database_path = _file_backed_database_path(self.database_path)
        temp_root = _resolved_temp_root(self.temp_root)
        _positive_byte_budget(self.memory_limit_bytes, "memory_limit_bytes")
        _positive_byte_budget(
            self.max_temp_directory_size_bytes,
            "max_temp_directory_size_bytes",
        )
        object.__setattr__(self, "database_path", database_path)
        object.__setattr__(self, "temp_root", temp_root)


@dataclass
class BoundedSplinkLinker:
    """Splink linker coupled to the bounded connection it exclusively owns."""

    linker: Any
    _connection: Any

    def close(self) -> None:
        self._connection.close()


def _file_backed_database_path(value: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.name in {"", ":memory:"}:
        raise ValueError("database_path must be an absolute file-backed DuckDB artifact")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as error:
        raise ValueError("database_path parent must exist and be resolved") from error
    resolved_path = resolved_parent / path.name
    if resolved_path != path:
        raise ValueError("database_path must already be resolved")
    if path.exists() and not path.is_file():
        raise ValueError("database_path must identify a file-backed DuckDB artifact")
    return path


def _resolved_temp_root(value: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("temp_root must be absolute")
    if path.name == ".tmp":
        raise ValueError("temp_root must not use DuckDB's default .tmp directory")
    try:
        resolved_path = path.resolve(strict=True)
    except OSError as error:
        raise ValueError("temp_root must exist and be resolved") from error
    if resolved_path != path or not path.is_dir():
        raise ValueError("temp_root must be a resolved directory")
    return path


def _positive_byte_budget(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer byte budget")


def _duckdb_size_bytes(value: str, setting_name: str) -> int:
    match = _DUCKDB_SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise RuntimeError(f"DuckDB returned an unsupported {setting_name} value: {value!r}")
    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation as error:
        raise RuntimeError(f"DuckDB returned an invalid {setting_name} value: {value!r}") from error
    return int(amount * _DUCKDB_SIZE_UNITS[match.group("unit")])


def _current_setting(connection: Any, setting_name: str) -> str:
    row = connection.execute("SELECT current_setting(?)", [setting_name]).fetchone()
    if row is None or len(row) != 1:
        raise RuntimeError(f"DuckDB did not return the effective {setting_name} setting")
    return str(row[0])


def _verify_bounded_settings(
    connection: Any,
    config: BoundedDuckDBConfig,
) -> None:
    effective_temp_root = Path(_current_setting(connection, "temp_directory")).resolve(strict=False)
    effective_memory_bytes = _duckdb_size_bytes(
        _current_setting(connection, "memory_limit"),
        "memory_limit",
    )
    effective_temp_bytes = _duckdb_size_bytes(
        _current_setting(connection, "max_temp_directory_size"),
        "max_temp_directory_size",
    )
    if effective_temp_root != config.temp_root:
        raise RuntimeError("DuckDB temp_directory is outside configured temp root")
    if effective_memory_bytes > config.memory_limit_bytes:
        raise RuntimeError("DuckDB memory_limit is looser than the requested byte budget")
    if effective_temp_bytes > config.max_temp_directory_size_bytes:
        raise RuntimeError("DuckDB max_temp_directory_size is looser than the requested byte budget")


def open_bounded_duckdb_connection(
    config: BoundedDuckDBConfig,
    *,
    connection_opener: Callable[[str], Any] | None = None,
) -> Any:
    """Open and prove one file-backed DuckDB connection within explicit budgets."""
    if connection_opener is None:
        import duckdb

        connection_opener = duckdb.connect

    connection = connection_opener(str(config.database_path))
    try:
        connection.execute("SET temp_directory = ?", [str(config.temp_root)])
        connection.execute("SET memory_limit = ?", [f"{config.memory_limit_bytes}B"])
        connection.execute(
            "SET max_temp_directory_size = ?",
            [f"{config.max_temp_directory_size_bytes}B"],
        )
        _verify_bounded_settings(connection, config)
    except Exception:
        connection.close()
        raise
    return connection


def _coerce_input_table_dtypes(input_table: Any) -> Any:
    """Force non-date columns to pandas string dtype.

    Prevents DuckDB from inferring INTEGER for all-null text columns during
    Splink table registration.
    """
    import pandas as pd

    for column in input_table.columns:
        if column in _DATETIME_COLUMNS:
            input_table[column] = pd.to_datetime(input_table[column], errors="coerce")
            continue
        input_table[column] = input_table[column].astype("string")

    return input_table


def build_splink_linker(
    prepared_rows: list[dict[str, Any]],
    settings: Any,
    *,
    runtime_resolver: Callable[[], tuple[type[Any], type[Any]]] | None = None,
    bounded_connection_factory: BoundedConnectionFactory | None = None,
) -> Any | BoundedSplinkLinker:
    """Construct a Splink Linker with properly registered input data.

    Splink 4 expects registered table names, not raw row lists. When the DB
    API exposes ``register_table`` the rows are loaded as a pandas DataFrame
    first; older shims fall back to passing rows directly.
    """
    resolve_runtime = runtime_resolver or get_splink_runtime
    Linker, DuckDBAPI = resolve_runtime()
    uses_bounded_connection = bounded_connection_factory is not None
    connection = bounded_connection_factory() if bounded_connection_factory else None
    if uses_bounded_connection and connection is None:
        raise RuntimeError("bounded_connection_factory must return a DuckDB connection")
    try:
        db_api = DuckDBAPI(connection=connection) if uses_bounded_connection else DuckDBAPI()
        linker = _register_rows_and_build_linker(
            prepared_rows,
            settings,
            linker_type=Linker,
            db_api=db_api,
        )
    except Exception:
        if uses_bounded_connection:
            connection.close()
        raise

    if uses_bounded_connection:
        return BoundedSplinkLinker(linker=linker, _connection=connection)
    return linker


def _register_rows_and_build_linker(
    prepared_rows: list[dict[str, Any]],
    settings: Any,
    *,
    linker_type: type[Any],
    db_api: Any,
) -> Any:
    """Register prepared rows through one DB API and construct its linker."""
    register_table = getattr(db_api, "register_table", None)
    if callable(register_table):
        import pandas as pd

        input_table = _coerce_input_table_dtypes(pd.DataFrame(prepared_rows))
        input_table_name = "__splink_input_rows"
        register_table(input_table, input_table_name, overwrite=True)
        return linker_type(input_table_name, settings, db_api)

    return linker_type(prepared_rows, settings, db_api)


def get_splink_runtime() -> tuple[type[Any], type[Any]]:
    """Return Splink runtime classes (Linker, DuckDBAPI)."""
    try:
        from splink import DuckDBAPI, Linker
    except (ImportError, ModuleNotFoundError):
        try:
            from splink.internals.duckdb.database_api import DuckDBAPI
            from splink.internals.linker import Linker
        except (ImportError, ModuleNotFoundError) as import_error:
            raise RuntimeError(
                "Splink runtime is required for probabilistic scoring. Install with `pip install splink duckdb`."
            ) from import_error

    return Linker, DuckDBAPI


def require_probabilistic_settings(settings: Any, *, entity_type: str) -> Any:
    """Fail fast when Splink settings are unavailable for the requested entity type."""
    if settings is None:
        raise RuntimeError(
            f"Splink settings are unavailable for {entity_type!r}. Install with `pip install splink duckdb`."
        )
    return settings


def _is_no_pair_training_error(error: Exception) -> bool:
    message = str(error).lower()
    return "no record pairs" in message


def train_linker(linker: Any, blocking_rules: list[Any]) -> None:
    """Run baseline EM training for Splink predictions."""
    training = getattr(linker, "training", None)
    if training is None:
        raise RuntimeError("Splink Linker is missing a training interface.")

    training.estimate_u_using_random_sampling(max_pairs=1_000_000)
    for blocking_rule in blocking_rules:
        try:
            training.estimate_parameters_using_expectation_maximisation(blocking_rule)
            return
        except Exception as error:
            if not _is_no_pair_training_error(error):
                raise


def prediction_records(predictions: Any) -> list[dict[str, Any]]:
    """Normalize Splink prediction output into a list of dictionaries."""
    if hasattr(predictions, "as_record_dict"):
        return list(predictions.as_record_dict())

    if hasattr(predictions, "to_dict"):
        records = predictions.to_dict(orient="records")
        return list(records)

    if hasattr(predictions, "as_pandas_dataframe"):
        dataframe = predictions.as_pandas_dataframe()
        return list(dataframe.to_dict(orient="records"))

    raise RuntimeError("Unsupported Splink prediction output format.")
