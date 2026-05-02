from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import core.keel_gate_l10 as keel_gate_l10


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_write_l10_evidence_marks_pass_when_all_fixture_routes_pass(tmp_path: Path) -> None:
    evidence_path = keel_gate_l10.write_l10_evidence(
        scope="NC",
        results=[
            keel_gate_l10.L10CaseResult(route="/candidate/empty", case_type="empty", passed=True),
            keel_gate_l10.L10CaseResult(route="/candidate/deviant", case_type="deviation", passed=True),
            keel_gate_l10.L10CaseResult(route="/candidate/alabama", case_type="al", passed=True),
            keel_gate_l10.L10CaseResult(route="/candidate/georgia", case_type="ga", passed=True),
        ],
        repo_sha="624e23b9",
        produced_at=datetime(2026, 4, 24, 6, 30, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert payload["schema_version"] == 2
    assert payload["status"] == "pass"
    assert payload["scope"] == "NC"
    assert payload["evaluated_routes"] == 4
    assert payload["empty_banner_cases"] == 1
    assert payload["deviation_banner_cases"] == 1
    assert payload["al_freshness_note_cases"] == 1
    assert payload["ga_freshness_note_cases"] == 1
    assert payload["failing_routes"] == []


def test_write_l10_evidence_marks_fail_and_lists_failing_routes(tmp_path: Path) -> None:
    evidence_path = keel_gate_l10.write_l10_evidence(
        scope="NC",
        results=[
            keel_gate_l10.L10CaseResult(route="/candidate/empty", case_type="empty", passed=True),
            keel_gate_l10.L10CaseResult(route="/candidate/deviant", case_type="deviation", passed=False),
            keel_gate_l10.L10CaseResult(
                route="/candidate/abababab-abab-4aba-8aba-abababababab",
                case_type="al",
                passed=False,
            ),
            keel_gate_l10.L10CaseResult(
                route="/candidate/cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd",
                case_type="ga",
                passed=True,
            ),
        ],
        repo_sha="624e23b9",
        produced_at=datetime(2026, 4, 24, 6, 30, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert payload["schema_version"] == 2
    assert payload["status"] == "fail"
    assert payload["failing_routes"] == [
        "/candidate/deviant",
        "/candidate/abababab-abab-4aba-8aba-abababababab",
    ]


def test_main_runs_fixture_cases_and_writes_fail_evidence_for_any_failed_case(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixed_now = datetime(2026, 4, 24, 6, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(keel_gate_l10, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(keel_gate_l10, "_repo_sha", lambda: "624e23b9")
    monkeypatch.setattr(
        keel_gate_l10,
        "run_l10_case",
        lambda case, *, web_root: keel_gate_l10.L10CaseResult(
            route=case.route,
            case_type=case.case_type,
            passed=case.case_type in {"empty", "ga"},
        ),
    )

    (tmp_path / "web" / "node_modules").mkdir(parents=True)

    exit_code = keel_gate_l10.main(
        [
            "--scope",
            "NC",
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--web-root",
            str(tmp_path / "web"),
        ]
    )

    payload = _read_json(tmp_path / "evidence" / "NC" / f"{fixed_now.date().isoformat()}.json")

    assert exit_code == 1
    assert payload["schema_version"] == 2
    assert payload["status"] == "fail"
    assert payload["evaluated_routes"] == 4
    assert payload["empty_banner_cases"] == 1
    assert payload["deviation_banner_cases"] == 1
    assert payload["al_freshness_note_cases"] == 1
    assert payload["ga_freshness_note_cases"] == 1
    assert payload["failing_routes"] == [
        "/candidate/dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "/candidate/abababab-abab-4aba-8aba-abababababab",
    ]


def test_main_fails_fast_when_web_node_modules_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    fixed_now = datetime(2026, 4, 24, 6, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(keel_gate_l10, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(keel_gate_l10, "_repo_sha", lambda: "624e23b9")

    executed_routes: list[str] = []

    def _fake_run(case: keel_gate_l10.L10RouteCase, *, web_root: Path) -> keel_gate_l10.L10CaseResult:
        executed_routes.append(case.route)
        return keel_gate_l10.L10CaseResult(route=case.route, case_type=case.case_type, passed=True)

    monkeypatch.setattr(keel_gate_l10, "run_l10_case", _fake_run)
    (tmp_path / "web").mkdir(parents=True)

    exit_code = keel_gate_l10.main(
        [
            "--scope",
            "NC",
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--web-root",
            str(tmp_path / "web"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "infra/scripts/bootstrap_l10_gate.sh" in captured.err
    assert executed_routes == []
    assert not (tmp_path / "evidence" / "NC" / f"{fixed_now.date().isoformat()}.json").exists()


def test_main_runs_all_l10_cases_when_web_node_modules_exists(monkeypatch, tmp_path: Path) -> None:
    fixed_now = datetime(2026, 4, 24, 6, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(keel_gate_l10, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(keel_gate_l10, "_repo_sha", lambda: "624e23b9")

    executed_routes: list[str] = []

    def _fake_run(case: keel_gate_l10.L10RouteCase, *, web_root: Path) -> keel_gate_l10.L10CaseResult:
        executed_routes.append(case.route)
        return keel_gate_l10.L10CaseResult(route=case.route, case_type=case.case_type, passed=True)

    monkeypatch.setattr(keel_gate_l10, "run_l10_case", _fake_run)
    (tmp_path / "web" / "node_modules").mkdir(parents=True)

    exit_code = keel_gate_l10.main(
        [
            "--scope",
            "NC",
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--web-root",
            str(tmp_path / "web"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "NC" / f"{fixed_now.date().isoformat()}.json"
    payload = _read_json(evidence_path)

    assert exit_code == 0
    assert executed_routes == [case.route for case in keel_gate_l10._L10_CASES]
    assert payload["status"] == "pass"
    assert payload["evaluated_routes"] == len(keel_gate_l10._L10_CASES)
