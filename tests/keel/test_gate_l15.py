from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from jsonschema.validators import validator_for

import core.keel_gate_l15 as keel_gate_l15


REPO_ROOT = Path(__file__).resolve().parents[2]
L15_SCHEMA_PATH = REPO_ROOT / "evidence_schemas" / "L15.json"
CORPUS_PATH = REPO_ROOT / "tests" / "regression_corpus.yaml"


def test_load_corpus_uses_repo_owned_campaign_finance_routes_and_bundles() -> None:
    corpus = keel_gate_l15.load_l15_corpus(CORPUS_PATH)

    assert [case.case_id for case in corpus] == [
        "candidate_detail_route",
        "committee_detail_route",
        "candidate_summary_total_raised",
        "committee_summary_total_raised",
    ]
    owner_symbols = {symbol for case in corpus for symbol in case.owner_symbols}
    assert "loadCampaignFinanceDetailPage" in owner_symbols
    assert "fetchCandidateDetailBundle" in owner_symbols
    assert "fetchCommitteeDetailBundle" in owner_symbols
    assert corpus[0].expected_value == "Pat Candidate"
    assert corpus[1].expected_value == "Citizens for Civibus"
    assert corpus[2].expected_value == "250.00"
    assert corpus[3].expected_value == "125.00"
    # Each case must single-source its fixture mapping in the corpus YAML, not in code.
    for case in corpus:
        assert case.fixture_export, f"case {case.case_id} missing fixture_export"
        assert case.fixture_value_pattern, f"case {case.case_id} missing fixture_value_pattern"


def test_in_code_case_fixture_registry_is_removed() -> None:
    # The duplicate registry that mirrored YAML cases in code is forbidden:
    # YAML is the single source of truth for case to fixture mapping.
    assert not hasattr(keel_gate_l15, "_CASE_FIXTURE_SOURCES")


def test_collect_observed_values_uses_route_fixture_owners() -> None:
    corpus = keel_gate_l15.load_l15_corpus(CORPUS_PATH)
    observed = keel_gate_l15.collect_observed_values(repo_root=REPO_ROOT, corpus=corpus)

    assert observed == {
        "candidate_detail_route": "Pat Candidate",
        "committee_detail_route": "Citizens for Civibus",
        "candidate_summary_total_raised": "250.00",
        "committee_summary_total_raised": "125.00",
    }


def test_execute_corpus_is_deterministic_and_normalizes_numeric_values(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "z_case",
                        "layer": "L15",
                        "case_type": "api_bundle",
                        "route_path": "/z",
                        "owner_paths": ["web/src/lib/server/api/campaign-finance-detail.ts"],
                        "owner_symbols": ["fetchCommitteeSummary"],
                        "metric_name": "total_raised",
                        "expected_value": "12.50",
                        "fixture_export": "Z_DATA",
                        "fixture_value_pattern": "z=([0-9.]+)",
                    },
                    {
                        "case_id": "a_case",
                        "layer": "L15",
                        "case_type": "api_bundle",
                        "route_path": "/a",
                        "owner_paths": ["web/src/lib/server/api/campaign-finance-detail.ts"],
                        "owner_symbols": ["fetchCandidateSummary"],
                        "metric_name": "total_raised",
                        "expected_value": "5.00",
                        "fixture_export": "A_DATA",
                        "fixture_value_pattern": "a=([0-9.]+)",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    corpus = keel_gate_l15.load_l15_corpus(corpus_path)
    summary = keel_gate_l15.execute_corpus(
        corpus=corpus,
        observed_values={
            "z_case": 12.5,
            "a_case": "5.000",
        },
    )

    assert [result.case_id for result in summary.results] == ["a_case", "z_case"]
    assert summary.results[0].normalized_expected == "5.00"
    assert summary.results[0].normalized_observed == "5.00"
    assert summary.results[1].normalized_expected == "12.50"
    assert summary.results[1].normalized_observed == "12.50"


def test_sync_l15_findings_reuses_l7_owner_seam(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    findings_root = tmp_path / "findings"
    findings_root.mkdir(parents=True)

    summary = keel_gate_l15.L15RunSummary(
        total_cases=1,
        failing_cases=1,
        results=[
            keel_gate_l15.L15CaseResult(
                case_id="candidate_summary_total_raised",
                case_type="api_bundle",
                route_path="/v1/candidates/1/summary",
                metric_name="total_raised",
                normalized_expected="12345.67",
                normalized_observed="12300.00",
                passed=False,
            )
        ],
    )

    captured: dict[str, object] = {}

    def _fake_sync_findings_section(
        *,
        findings_root: Path,
        evidence_date: date,
        section_start: str,
        section_end: str,
        section_text: str,
    ) -> Path:
        captured["findings_root"] = findings_root
        captured["evidence_date"] = evidence_date
        captured["section_start"] = section_start
        captured["section_end"] = section_end
        captured["section_text"] = section_text
        target = findings_root / f"{evidence_date.isoformat()}.md"
        target.write_text("# Keel Findings - 2026-04-25\n", encoding="utf-8")
        return target

    monkeypatch.setattr(keel_gate_l15, "sync_findings_section", _fake_sync_findings_section)

    written_path = keel_gate_l15.sync_l15_findings(
        findings_root=findings_root, evidence_date=date(2026, 4, 25), summary=summary
    )

    assert written_path == findings_root / "2026-04-25.md"
    assert captured["findings_root"] == findings_root
    assert captured["evidence_date"] == date(2026, 4, 25)
    assert captured["section_start"] == "<!-- keel:L15:start -->"
    assert captured["section_end"] == "<!-- keel:L15:end -->"
    assert "candidate_summary_total_raised" in str(captured["section_text"])


def test_write_l15_evidence_emits_schema_valid_payload(tmp_path: Path) -> None:
    summary = keel_gate_l15.L15RunSummary(
        total_cases=2,
        failing_cases=0,
        results=[
            keel_gate_l15.L15CaseResult(
                case_id="candidate_detail_route",
                case_type="route_render",
                route_path="/candidate/1",
                metric_name="candidate_display_name",
                normalized_expected="Candidate Example",
                normalized_observed="Candidate Example",
                passed=True,
            ),
            keel_gate_l15.L15CaseResult(
                case_id="committee_summary_total_raised",
                case_type="api_bundle",
                route_path="/v1/committees/2/summary",
                metric_name="total_raised",
                normalized_expected="67890.12",
                normalized_observed="67890.12",
                passed=True,
            ),
        ],
    )
    evidence_path = keel_gate_l15.write_l15_evidence(
        repo_root=REPO_ROOT,
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 25),
        produced_at=datetime(2026, 4, 25, 13, 30, tzinfo=UTC),
        summary=summary,
        gate_command="python -m core.keel_gate_l15 --corpus-path tests/regression_corpus.yaml",
        repo_sha="abcd1234",
    )

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    schema = json.loads(L15_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    assert list(validator.iter_errors(payload)) == []


def test_main_is_byte_stable_for_same_fixture_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    corpus_path = repo_root / "tests" / "regression_corpus.yaml"
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(CORPUS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    fixture_sources = [
        "web/src/lib/campaign-finance-detail/route-render.test-fixtures.ts",
        "web/src/lib/campaign-finance-detail/contract.ts",
        "web/src/lib/campaign-finance-detail/page-load.ts",
        "web/src/lib/server/api/campaign-finance-detail.ts",
        "web/src/routes/candidate/[id]/+page.server.ts",
        "web/src/routes/committee/[id]/+page.server.ts",
    ]
    for relative_path in fixture_sources:
        source_path = REPO_ROOT / relative_path
        target_path = repo_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    monkeypatch.setattr(keel_gate_l15, "_utc_now", lambda: datetime(2026, 4, 25, 12, 0, tzinfo=UTC))
    monkeypatch.setattr(keel_gate_l15, "_repo_sha", lambda repo_root: "abc12345")

    args = [
        "--repo-root",
        str(repo_root),
        "--date",
        "2026-04-25",
        "--corpus-path",
        str(corpus_path),
        "--evidence-root",
        str(repo_root / "evidence" / "L15"),
        "--findings-root",
        str(repo_root / "findings"),
    ]

    first_exit = keel_gate_l15.main(args)
    first_evidence = (repo_root / "evidence" / "L15" / "global" / "2026-04-25.json").read_bytes()
    first_findings = (repo_root / "findings" / "2026-04-25.md").read_bytes()

    second_exit = keel_gate_l15.main(args)
    second_evidence = (repo_root / "evidence" / "L15" / "global" / "2026-04-25.json").read_bytes()
    second_findings = (repo_root / "findings" / "2026-04-25.md").read_bytes()

    assert first_exit == 0
    assert second_exit == 0
    assert first_evidence == second_evidence
    assert first_findings == second_findings


def test_build_argument_parser_does_not_require_observed_values_path() -> None:
    parser = keel_gate_l15.build_argument_parser()
    args = parser.parse_args([])

    assert not hasattr(args, "observed_values_path")
