from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest

from core.schema import test_contact_point_schema, test_provenance_schema


@pytest.mark.parametrize(
    "schema_tests",
    [test_contact_point_schema, test_provenance_schema],
)
def test_skip_if_no_database_access_skips_when_database_is_optional(
    monkeypatch: pytest.MonkeyPatch,
    schema_tests: ModuleType,
) -> None:
    monkeypatch.delenv("CIVIBUS_REQUIRE_DB", raising=False)
    _mock_database_probe(monkeypatch, schema_tests, RuntimeError("connection refused"))

    with pytest.raises(pytest.skip.Exception, match="Unable to connect to test database"):
        schema_tests._skip_if_no_database_access()


@pytest.mark.parametrize(
    "schema_tests",
    [test_contact_point_schema, test_provenance_schema],
)
def test_skip_if_no_database_access_fails_when_database_is_required(
    monkeypatch: pytest.MonkeyPatch,
    schema_tests: ModuleType,
) -> None:
    monkeypatch.setenv("CIVIBUS_REQUIRE_DB", "1")
    _mock_database_probe(monkeypatch, schema_tests, RuntimeError("connection refused"))

    try:
        schema_tests._skip_if_no_database_access()
    except pytest.skip.Exception as exc:
        pytest.fail(f"expected required database failure, got skip: {exc}")
    except pytest.fail.Exception as exc:
        assert "Unable to connect to test database" in str(exc)
    else:
        pytest.fail("expected required database failure")


def _mock_database_probe(
    monkeypatch: pytest.MonkeyPatch,
    schema_tests: ModuleType,
    error: RuntimeError,
) -> None:
    def _raise_connection_error(_database: str, _sql: str) -> list[str]:
        raise error

    probe: Callable[[str, str], list[str]] = _raise_connection_error
    monkeypatch.setitem(schema_tests._skip_if_no_database_access.__globals__, "_run_psql_command", probe)
