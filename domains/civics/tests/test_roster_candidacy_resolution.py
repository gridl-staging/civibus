from __future__ import annotations

import json

from domains.civics.scripts.roster_candidacy_resolution import _build_argument_parser, main


def test_argument_parser_accepts_auto_merge_threshold() -> None:
    parser = _build_argument_parser()
    args = parser.parse_args(["--auto-merge-threshold", "0.97"])

    assert args.auto_merge_threshold == 0.97


def test_main_emits_deterministic_json_summary(
    monkeypatch,
    capsys,
) -> None:
    captured_threshold: list[float | None] = []

    class _FakeConnection:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.close_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    fake_connection = _FakeConnection()

    monkeypatch.setattr(
        "domains.civics.scripts.roster_candidacy_resolution.get_connection",
        lambda: fake_connection,
    )

    def _fake_resolver(conn, *, auto_merge_threshold):
        assert conn is fake_connection
        captured_threshold.append(auto_merge_threshold)
        return {
            "candidate_pairs": 3,
            "linked_rows": 2,
            "skipped_rows": 1,
            "already_linked_rows": 0,
            "mutated_rows": 2,
        }

    monkeypatch.setattr(
        "domains.civics.scripts.roster_candidacy_resolution.resolve_roster_candidacy_people",
        _fake_resolver,
    )

    exit_code = main(["--auto-merge-threshold", "0.93"])

    assert exit_code == 0
    assert captured_threshold == [0.93]
    assert fake_connection.commit_calls == 1
    assert fake_connection.close_calls == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "candidate_pairs": 3,
        "linked_rows": 2,
        "skipped_rows": 1,
        "already_linked_rows": 0,
        "mutated_rows": 2,
    }
