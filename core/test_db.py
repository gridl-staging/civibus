from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from core.db import get_connection


def test_get_connection_reads_environment_values_and_supports_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")
    monkeypatch.setenv("POSTGRES_HOST", "env_host")
    monkeypatch.setenv("POSTGRES_PORT", "5544")

    mocked_connection = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        connection = get_connection(host="override_host", port=6000)

    assert connection is mocked_connection
    connect_mock.assert_called_once_with(
        user="env_user",
        password="env_password",
        dbname="env_database",
        host="override_host",
        port=6000,
    )
    assert mocked_connection.autocommit is False


def test_get_connection_runs_post_connect_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")

    mocked_connection = MagicMock()
    post_connect = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection):
        connection = get_connection(post_connect=post_connect)

    assert connection is mocked_connection
    post_connect.assert_called_once_with(mocked_connection)


def test_get_connection_raises_clear_runtime_error_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")
    monkeypatch.setenv("POSTGRES_HOST", "db.local")
    monkeypatch.setenv("POSTGRES_PORT", "5432")

    with patch(
        "core.db.psycopg.connect",
        side_effect=psycopg.OperationalError("connection failed"),
    ):
        with pytest.raises(RuntimeError, match="Unable to connect to PostgreSQL at db.local:5432/env_database"):
            get_connection()


def test_get_connection_closes_connection_when_post_connect_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")

    mocked_connection = MagicMock()

    def failing_post_connect(_: MagicMock) -> None:
        raise RuntimeError("post-connect hook failed")

    with patch("core.db.psycopg.connect", return_value=mocked_connection):
        with pytest.raises(RuntimeError, match="post-connect hook failed"):
            get_connection(post_connect=failing_post_connect)

    mocked_connection.close.assert_called_once()


def test_get_connection_remaps_docker_hostname_db_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSTGRES_HOST=db (Docker service name) should resolve to 127.0.0.1 for host-level execution."""
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")

    mocked_connection = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        get_connection()

    connect_mock.assert_called_once_with(
        user="env_user",
        password="env_password",
        dbname="env_database",
        host="127.0.0.1",
        port=5432,
    )


def test_get_connection_keeps_docker_hostname_inside_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSTGRES_HOST=db should remain db when code runs inside a container."""
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")

    mocked_connection = MagicMock()
    monkeypatch.setattr("core.db.os.path.exists", lambda path: path == "/.dockerenv")

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        get_connection()

    connect_mock.assert_called_once_with(
        user="env_user",
        password="env_password",
        dbname="env_database",
        host="db",
        port=5432,
    )
