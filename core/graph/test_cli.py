from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from core.graph.cli import _build_argument_parser, age_post_connect, load_cf_edges, main


class TestLoadCfEdges:
    def test_calls_stage3_loaders_in_order_with_shared_limit(self, capsys: pytest.CaptureFixture[str]):
        conn = MagicMock()
        manager = MagicMock()

        with (
            patch("core.graph.cli.load_contributed_to_edges", return_value=2) as contributed,
            patch("core.graph.cli.load_spent_on_edges", return_value=0) as spent,
            patch("core.graph.cli.load_ie_edges", return_value=4) as ie_edges,
            patch("core.graph.cli.load_affiliated_with_edges", return_value=1) as affiliated,
            patch("core.graph.cli.load_filed_edges", return_value=3) as filed,
        ):
            manager.attach_mock(contributed, "contributed")
            manager.attach_mock(spent, "spent")
            manager.attach_mock(ie_edges, "ie_edges")
            manager.attach_mock(affiliated, "affiliated")
            manager.attach_mock(filed, "filed")

            total = load_cf_edges(conn, limit=25)

        assert total == 10
        assert manager.mock_calls == [
            call.contributed(conn, limit=25),
            call.spent(conn, limit=25),
            call.ie_edges(conn, limit=25),
            call.affiliated(conn, limit=25),
            call.filed(conn, limit=25),
        ]
        assert conn.commit.call_count == 0

        lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert lines == [
            "Loaded CONTRIBUTED_TO edge(s): 2",
            "Loaded SPENT_ON edge(s): 0",
            "Loaded SUPPORTS/OPPOSES edge(s): 4",
            "Loaded AFFILIATED_WITH edge(s): 1",
            "Loaded FILED edge(s): 3",
            "Loaded total campaign-finance edge(s): 10",
        ]

    def test_propagates_loader_failures(self):
        conn = MagicMock()
        with (
            patch("core.graph.cli.load_contributed_to_edges", return_value=2),
            patch("core.graph.cli.load_spent_on_edges", side_effect=RuntimeError("spent loader failed")),
            patch("core.graph.cli.load_ie_edges", return_value=4),
            patch("core.graph.cli.load_affiliated_with_edges", return_value=1),
            patch("core.graph.cli.load_filed_edges", return_value=3),
        ):
            with pytest.raises(RuntimeError, match="spent loader failed"):
                load_cf_edges(conn, limit=10)


class TestMain:
    def test_main_passes_limit_to_mixed_domain_loaders_and_commits_once(
        self,
        capsys: pytest.CaptureFixture[str],
    ):
        mock_conn = MagicMock()
        manager = MagicMock()
        with (
            patch("core.graph.cli.get_connection", return_value=mock_conn) as mock_get_connection,
            patch("core.graph.cli.load_cf_edges", return_value=7) as mock_cf_load,
            patch("core.graph.cli.load_property_edges", return_value=5) as mock_property_load,
            patch("core.graph.cli.load_civic_edges", return_value=3) as mock_civic_load,
        ):
            manager.attach_mock(mock_cf_load, "cf")
            manager.attach_mock(mock_property_load, "property")
            manager.attach_mock(mock_civic_load, "civic")
            result = main(["--limit", "10"])

        assert result == 0
        mock_get_connection.assert_called_once_with(post_connect=age_post_connect)
        assert manager.mock_calls == [
            call.cf(mock_conn, limit=10),
            call.property(mock_conn, limit=10),
            call.civic(mock_conn, limit=10),
        ]
        mock_conn.commit.assert_called_once_with()
        mock_conn.close.assert_called_once_with()
        output = capsys.readouterr().out
        assert "Loaded campaign-finance edge(s): 7" in output
        assert "Loaded property edge(s): 5" in output
        assert "Loaded civic edge(s): 3" in output
        assert "Loaded total edge(s) into AGE graph: 15" in output

    def test_main_returns_one_without_commit_on_loader_failure(self, capsys: pytest.CaptureFixture[str]):
        mock_conn = MagicMock()
        with (
            patch("core.graph.cli.get_connection", return_value=mock_conn),
            patch("core.graph.cli.load_cf_edges", side_effect=RuntimeError("boom")),
            patch("core.graph.cli.load_property_edges", return_value=5) as mock_property_load,
            patch("core.graph.cli.load_civic_edges", return_value=0) as mock_civic_load,
        ):
            result = main(["--limit", "10"])

        assert result == 1
        mock_property_load.assert_not_called()
        mock_civic_load.assert_not_called()
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once_with()
        captured = capsys.readouterr()
        assert "Graph load failed:" in captured.err
        assert "boom" in captured.err

    def test_main_returns_one_without_commit_on_property_loader_failure(self, capsys: pytest.CaptureFixture[str]):
        mock_conn = MagicMock()
        with (
            patch("core.graph.cli.get_connection", return_value=mock_conn),
            patch("core.graph.cli.load_cf_edges", return_value=7),
            patch("core.graph.cli.load_property_edges", side_effect=RuntimeError("property boom")),
            patch("core.graph.cli.load_civic_edges", return_value=0),
        ):
            result = main(["--limit", "10"])

        assert result == 1
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once_with()
        captured = capsys.readouterr()
        assert "Graph load failed:" in captured.err
        assert "property boom" in captured.err

    def test_main_returns_one_when_connection_fails(self, capsys: pytest.CaptureFixture[str]):
        with patch("core.graph.cli.get_connection", side_effect=RuntimeError("db down")) as mock_get_connection:
            result = main(["--limit", "10"])

        assert result == 1
        mock_get_connection.assert_called_once_with(post_connect=age_post_connect)
        captured = capsys.readouterr()
        assert "Graph load failed:" in captured.err
        assert "db down" in captured.err

    def test_main_uses_default_limit(self):
        mock_conn = MagicMock()
        with (
            patch("core.graph.cli.get_connection", return_value=mock_conn),
            patch("core.graph.cli.load_cf_edges", return_value=0) as mock_cf_load,
            patch("core.graph.cli.load_property_edges", return_value=0) as mock_property_load,
            patch("core.graph.cli.load_civic_edges", return_value=0) as mock_civic_load,
        ):
            result = main([])

        assert result == 0
        mock_cf_load.assert_called_once_with(mock_conn, limit=1000)
        mock_property_load.assert_called_once_with(mock_conn, limit=1000)
        mock_civic_load.assert_called_once_with(mock_conn, limit=1000)

    def test_parser_help_mentions_graph_load_entrypoint(self):
        parser = _build_argument_parser()
        help_text = parser.format_help()

        assert "graph-load" in help_text
        assert "property" in help_text
        assert "civics" in help_text
        assert "--limit" in help_text
