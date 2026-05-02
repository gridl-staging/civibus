from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.queries.civics import fetch_electoral_division_geometries

pytestmark = pytest.mark.unit


def test_fetch_electoral_division_geometries_uses_latest_boundary_year_filter() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor

    connection = MagicMock()
    connection.cursor.return_value = cursor_context

    fetch_electoral_division_geometries(connection, level="county", state="NC")

    executed_sql, executed_params = cursor.execute.call_args.args
    assert "MAX(boundary_year)" in executed_sql
    assert executed_params == ("county", "NC", "county", "NC")
