from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from core.db import build_connection_parameters, connection_identity, get_connection


def _set_connection_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_DB", "env_database")
    monkeypatch.setenv("POSTGRES_HOST", "env_host")
    monkeypatch.setenv("POSTGRES_PORT", "5544")


def test_get_connection_forwards_explicit_application_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_connection_environment(monkeypatch)
    mocked_connection = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        connection = get_connection(application_name="refresh:explicit")

    assert connection is mocked_connection
    connect_mock.assert_called_once_with(
        user="env_user",
        password="env_password",
        dbname="env_database",
        host="env_host",
        port=5544,
        application_name="refresh:explicit",
    )


def test_unscoped_connection_parameters_preserve_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_connection_environment(monkeypatch)

    assert build_connection_parameters() == {
        "user": "env_user",
        "password": "env_password",
        "dbname": "env_database",
        "host": "env_host",
        "port": 5544,
    }


def test_get_connection_inherits_ambient_application_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_connection_environment(monkeypatch)
    mocked_connection = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        with connection_identity("refresh:ambient"):
            get_connection()

    assert connect_mock.call_args.kwargs["application_name"] == "refresh:ambient"


def test_explicit_application_name_wins_over_ambient_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_connection_environment(monkeypatch)
    mocked_connection = MagicMock()

    with patch("core.db.psycopg.connect", return_value=mocked_connection) as connect_mock:
        with connection_identity("refresh:ambient"):
            get_connection(application_name="refresh:explicit")

    assert connect_mock.call_args.kwargs["application_name"] == "refresh:explicit"


def test_valid_explicit_application_name_supersedes_invalid_ambient_identity() -> None:
    with connection_identity("a" * 64):
        parameters = build_connection_parameters(application_name="refresh:explicit")

    assert parameters["application_name"] == "refresh:explicit"


def test_nested_connection_identity_restores_outer_identity() -> None:
    with connection_identity("refresh:outer"):
        assert build_connection_parameters()["application_name"] == "refresh:outer"
        with connection_identity("refresh:inner"):
            assert build_connection_parameters()["application_name"] == "refresh:inner"
        assert build_connection_parameters()["application_name"] == "refresh:outer"

    assert "application_name" not in build_connection_parameters()


def test_connection_identity_restores_state_after_exception() -> None:
    with pytest.raises(RuntimeError, match="deliberate failure"):
        with connection_identity("refresh:exception"):
            assert build_connection_parameters()["application_name"] == "refresh:exception"
            raise RuntimeError("deliberate failure")

    assert "application_name" not in build_connection_parameters()


def test_application_name_accepts_postgresql_63_byte_limit() -> None:
    application_name = "a" * 63

    assert build_connection_parameters(application_name=application_name)["application_name"] == application_name


@pytest.mark.parametrize(
    "invalid_application_name",
    [
        "a" * 64,
        "\u00e9" * 32,
    ],
)
def test_invalid_explicit_application_name_does_not_connect(invalid_application_name: str) -> None:
    with patch("core.db.psycopg.connect") as connect_mock:
        with pytest.raises(ValueError, match="63 bytes"):
            get_connection(application_name=invalid_application_name)

    connect_mock.assert_not_called()


def test_invalid_ambient_application_name_does_not_connect() -> None:
    with patch("core.db.psycopg.connect") as connect_mock:
        with connection_identity("\u00e9" * 32):
            with pytest.raises(ValueError, match="63 bytes"):
                get_connection()

    connect_mock.assert_not_called()


def test_get_connection_reads_environment_values_and_supports_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_connection_environment(monkeypatch)

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
