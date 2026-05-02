from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import core.keel_gate_l9 as keel_gate_l9
from api.models.provenance import SourceInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
_L9_SCHEMA_PATH = _REPO_ROOT / "evidence_schemas" / "L9.json"


def _load_l9_schema() -> dict[str, object]:
    return json.loads(_L9_SCHEMA_PATH.read_text(encoding="utf-8"))


def _build_source_info(
    *,
    data_source_url: str = "https://example.org/data-source",
    record_url: str | None = "https://example.org/record",
    data_source_name: str = "North Carolina Campaign Finance",
    source_record_key: str = "record-1",
) -> SourceInfo:
    return SourceInfo.model_validate(
        {
            "domain": "campaign_finance",
            "jurisdiction": "state/NC",
            "data_source_name": data_source_name,
            "data_source_url": data_source_url,
            "source_record_key": source_record_key,
            "record_url": record_url,
            "pull_date": datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        }
    )


def _build_trace_target(
    *,
    route: str,
    detail_id: str,
    target_type: str,
) -> keel_gate_l9.L9TraceTarget:
    return keel_gate_l9.L9TraceTarget(
        route=route,
        detail_id=detail_id,
        target_type=target_type,
    )


def test_l9_evidence_schema_round_trip_for_stage1_contract() -> None:
    schema = _load_l9_schema()
    assert schema["properties"]["layer"]["const"] == "L9"
    assert {
        "layer",
        "scope",
        "schema_version",
        "produced_at_utc",
        "repo_sha",
        "gate_command",
        "status",
        "sampled_record_count",
        "orphan_record_count",
        "sampled_records",
        "orphan_records",
    } <= set(schema["required"])

    evidence = keel_gate_l9.L9Evidence(
        layer="L9",
        scope="global",
        schema_version=1,
        produced_at_utc=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        repo_sha="624e23b9",
        gate_command="make gate-L9",
        status="pass",
        sampled_record_count=2,
        orphan_record_count=1,
        sampled_records=[
            keel_gate_l9.L9TraceSample(
                route="/v1/committees/00000000-0000-0000-0000-000000000001",
                detail_id="00000000-0000-0000-0000-000000000001",
                data_source_name="FEC Bulk",
                source_record_key="committee-source-1",
                selected_url="https://example.org/committee/1",
                selected_url_source="record_url",
            ),
            keel_gate_l9.L9TraceSample(
                route="/v1/offices/00000000-0000-0000-0000-000000000002",
                detail_id="00000000-0000-0000-0000-000000000002",
                data_source_name="North Carolina Campaign Finance",
                source_record_key="office-source-2",
                selected_url="https://example.org/source/2",
                selected_url_source="data_source_url",
            ),
        ],
        orphan_records=[
            keel_gate_l9.L9TraceOrphan(
                route="/v1/committees/00000000-0000-0000-0000-000000000003",
                detail_id="00000000-0000-0000-0000-000000000003",
                data_source_name="Unknown Source",
                source_record_key="committee-source-3",
                record_url="not-a-valid-url",
                data_source_url="ftp://example.org/not-allowed",
                orphan_reason="missing_safe_trace_url",
            )
        ],
    )

    payload = evidence.model_dump(mode="json")
    assert keel_gate_l9.L9Evidence.model_validate(payload).model_dump(mode="json") == payload


def test_resolve_trace_url_prefers_well_formed_record_url() -> None:
    resolved = keel_gate_l9.resolve_trace_url(_build_source_info())
    assert resolved == keel_gate_l9.ResolvedTraceUrl(
        url="https://example.org/record",
        url_source="record_url",
    )


def test_resolve_trace_url_falls_back_to_data_source_when_record_url_is_malformed() -> None:
    resolved = keel_gate_l9.resolve_trace_url(
        _build_source_info(
            data_source_url="https://example.org/data-source-fallback",
            record_url="javascript:alert(1)",
        )
    )
    assert resolved == keel_gate_l9.ResolvedTraceUrl(
        url="https://example.org/data-source-fallback",
        url_source="data_source_url",
    )


def test_resolve_trace_url_falls_back_to_data_source_when_record_url_is_missing() -> None:
    resolved = keel_gate_l9.resolve_trace_url(
        _build_source_info(
            data_source_url="https://example.org/data-source-missing-record",
            record_url=None,
        )
    )
    assert resolved == keel_gate_l9.ResolvedTraceUrl(
        url="https://example.org/data-source-missing-record",
        url_source="data_source_url",
    )


def test_resolve_trace_url_returns_none_when_no_safe_url_exists() -> None:
    assert (
        keel_gate_l9.resolve_trace_url(
            _build_source_info(
                data_source_url="ftp://example.org/not-http",
                record_url="not-a-valid-url",
            )
        )
        is None
    )


def test_collect_trace_report_uses_deterministic_sample_selection_for_same_inputs() -> None:
    targets = [
        _build_trace_target(
            route="/v1/offices/00000000-0000-0000-0000-000000000002",
            detail_id="00000000-0000-0000-0000-000000000002",
            target_type="office",
        ),
        _build_trace_target(
            route="/v1/committees/00000000-0000-0000-0000-000000000001",
            detail_id="00000000-0000-0000-0000-000000000001",
            target_type="committee",
        ),
    ]
    source_lookup = {
        (targets[0].target_type, targets[0].detail_id): [
            _build_source_info(
                data_source_name="Office Source",
                source_record_key="office-source",
                record_url=None,
                data_source_url="https://example.org/office",
            )
        ],
        (targets[1].target_type, targets[1].detail_id): [
            _build_source_info(
                data_source_name="Committee Source",
                source_record_key="committee-source",
                record_url="https://example.org/committee-record",
            )
        ],
    }

    def _load_sources(target: keel_gate_l9.L9TraceTarget) -> list[SourceInfo]:
        return source_lookup[(target.target_type, target.detail_id)]

    report_one = keel_gate_l9.collect_trace_report(targets, _load_sources)
    report_two = keel_gate_l9.collect_trace_report(list(reversed(targets)), _load_sources)

    assert [record.route for record in report_one.sampled_records] == [
        "/v1/committees/00000000-0000-0000-0000-000000000001",
        "/v1/offices/00000000-0000-0000-0000-000000000002",
    ]
    assert report_one == report_two


def test_build_argument_parser_rejects_non_positive_sample_limit() -> None:
    parser = keel_gate_l9.build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--sample-limit", "0"])

    with pytest.raises(SystemExit):
        parser.parse_args(["--sample-limit", "-1"])


def test_split_trace_target_limits_keeps_both_surfaces_in_scope_when_possible() -> None:
    assert keel_gate_l9._split_trace_target_limits(1) == (1, 0)
    assert keel_gate_l9._split_trace_target_limits(2) == (1, 1)
    assert keel_gate_l9._split_trace_target_limits(3) == (2, 1)
    assert keel_gate_l9._split_trace_target_limits(4) == (2, 2)


def test_main_writes_evidence_file_for_requested_date(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    report = keel_gate_l9.L9TraceReport(
        sampled_records=[
            keel_gate_l9.L9TraceSample(
                route="/v1/committees/00000000-0000-0000-0000-000000000001",
                detail_id="00000000-0000-0000-0000-000000000001",
                data_source_name="Committee Source",
                source_record_key="committee-source-1",
                selected_url="https://example.org/committee/1",
                selected_url_source="record_url",
            )
        ],
        orphan_records=[],
    )

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l9, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(keel_gate_l9, "build_trace_report", lambda connection, sample_limit=50: report)
    monkeypatch.setattr(keel_gate_l9, "_repo_sha", lambda repo_root: "4d5d4e5e")
    monkeypatch.setattr(
        keel_gate_l9,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 13, 30, tzinfo=timezone.utc),
    )

    exit_code = keel_gate_l9.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    evidence_path = repo_root / "evidence" / "L9" / "2026-04-24.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["sampled_record_count"] == 1
    assert payload["orphan_record_count"] == 0
    assert payload["sampled_records"][0]["selected_url"] == "https://example.org/committee/1"
    assert "PASS: sampled=1 orphans=0" in capsys.readouterr().out


def test_main_replaces_same_day_findings_block_idempotently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    findings_root = repo_root / "findings"
    findings_root.mkdir()
    findings_path = findings_root / "2026-04-24.md"
    findings_path.write_text(
        "# Keel Findings - 2026-04-24\n\nIntro text.\n\n<!-- keel:L9:start -->old<!-- keel:L9:end -->\n",
        encoding="utf-8",
    )

    report = keel_gate_l9.L9TraceReport(
        sampled_records=[],
        orphan_records=[
            keel_gate_l9.L9TraceOrphan(
                route="/v1/offices/00000000-0000-0000-0000-000000000002",
                detail_id="00000000-0000-0000-0000-000000000002",
                data_source_name="Office Source",
                source_record_key="office-source-2",
                record_url="javascript:alert(1)",
                data_source_url="https://example.org/office-source",
                orphan_reason="missing_safe_trace_url",
            )
        ],
    )

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l9, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(keel_gate_l9, "build_trace_report", lambda connection, sample_limit=50: report)
    monkeypatch.setattr(keel_gate_l9, "_repo_sha", lambda repo_root: "4d5d4e5e")
    monkeypatch.setattr(
        keel_gate_l9,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 13, 30, tzinfo=timezone.utc),
    )

    keel_gate_l9.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    findings_text = findings_path.read_text(encoding="utf-8")
    assert "<!-- keel:L9:start -->" in findings_text
    assert "old" not in findings_text
    assert "missing_safe_trace_url" in findings_text
    assert "office-source-2" in findings_text


def test_main_exit_code_is_nonzero_when_orphans_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    report = keel_gate_l9.L9TraceReport(
        sampled_records=[],
        orphan_records=[
            keel_gate_l9.L9TraceOrphan(
                route="/v1/offices/00000000-0000-0000-0000-000000000002",
                detail_id="00000000-0000-0000-0000-000000000002",
                data_source_name="Office Source",
                source_record_key="office-source-2",
                record_url="javascript:alert(1)",
                data_source_url="https://example.org/office-source",
                orphan_reason="missing_safe_trace_url",
            )
        ],
    )

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l9, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(keel_gate_l9, "build_trace_report", lambda connection, sample_limit=50: report)
    monkeypatch.setattr(keel_gate_l9, "_repo_sha", lambda repo_root: "4d5d4e5e")
    monkeypatch.setattr(
        keel_gate_l9,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 13, 30, tzinfo=timezone.utc),
    )

    assert keel_gate_l9.main(["--repo-root", str(repo_root), "--date", "2026-04-24"]) == 1
