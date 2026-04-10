from __future__ import annotations

from collections.abc import Callable
from typing import Any

_DATETIME_COLUMNS = {"date_of_birth"}


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
) -> Any:
    """Construct a Splink Linker with properly registered input data.

    Splink 4 expects registered table names, not raw row lists. When the DB
    API exposes ``register_table`` the rows are loaded as a pandas DataFrame
    first; older shims fall back to passing rows directly.
    """
    resolve_runtime = runtime_resolver or get_splink_runtime
    Linker, DuckDBAPI = resolve_runtime()
    db_api = DuckDBAPI()
    register_table = getattr(db_api, "register_table", None)
    if callable(register_table):
        import pandas as pd

        input_table = _coerce_input_table_dtypes(pd.DataFrame(prepared_rows))
        input_table_name = "__splink_input_rows"
        register_table(input_table, input_table_name, overwrite=True)
        return Linker(input_table_name, settings, db_api)

    return Linker(prepared_rows, settings, db_api)


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
