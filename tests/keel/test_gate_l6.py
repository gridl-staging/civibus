from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

import core.keel_gate_l6 as keel_gate_l6


_NC_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "domains"
    / "campaign_finance"
    / "jurisdictions"
    / "states"
    / "NC"
    / "tests"
    / "fixtures"
)
_NC_TRANSACTIONS_FIXTURE = _NC_FIXTURE_ROOT / "transaction_export_sample.csv"
_NC_COMMITTEE_DOCS_FIXTURE = _NC_FIXTURE_ROOT / "committee_document_export_sample.csv"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_main_writes_pass_evidence_for_valid_nc_transaction_fixture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(keel_gate_l6, "_repo_sha", lambda: "4a64e348")

    exit_code = keel_gate_l6.main(
        [
            "--jurisdiction",
            "NC",
            "--data-type",
            "transactions",
            "--path",
            str(_NC_TRANSACTIONS_FIXTURE),
            "--load-id",
            "nc-transactions-2026-04-24",
            "--load-date",
            "2026-04-24",
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "nc-transactions-2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["scope"] == "NC_transactions"
    assert payload["load_id"] == "nc-transactions-2026-04-24"
    assert payload["total_rows"] == 5
    assert payload["out_of_range_rows"] == 0
    assert payload["example_rows"] == []


def test_main_writes_pass_evidence_for_nc_pilot_fixture_suite(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(keel_gate_l6, "_repo_sha", lambda: "4a64e348")
    monkeypatch.setattr(
        keel_gate_l6,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 18, 30, tzinfo=timezone.utc),
    )

    exit_code = keel_gate_l6.main(
        [
            "--jurisdiction",
            "NC",
            "--pilot-fixture-suite",
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_root = tmp_path / "evidence"
    transaction_payload = _read_json(evidence_root / "nc-transactions-20260424T183000Z.json")
    committee_payload = _read_json(evidence_root / "nc-committee-documents-20260424T183000Z.json")
    ie_payload = _read_json(evidence_root / "nc-ie-document-index-20260424T183000Z.json")

    assert exit_code == 0
    assert (transaction_payload["scope"], transaction_payload["status"]) == ("NC_transactions", "pass")
    assert (committee_payload["scope"], committee_payload["status"]) == ("NC_committee_documents", "pass")
    assert (ie_payload["scope"], ie_payload["status"]) == ("NC_ie_document_index", "pass")


def test_main_writes_fail_evidence_when_committee_doc_dates_are_future_dated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(keel_gate_l6, "_repo_sha", lambda: "4a64e348")
    invalid_fixture = tmp_path / "future_committee_docs.csv"
    invalid_fixture.write_text(
        """Committee Name,SBoE ID,Year,Doc Type,Doc Name,Amend,Received Image,Received Data,Start Date,End Date,Image,Data
Future Committee,001-4L70LV-C-001,2026,Disclosure Report,Year End Semi-Annual,N,,04/30/2026,04/01/2026,04/15/2026,,DATA
""",
        encoding="utf-8",
    )

    exit_code = keel_gate_l6.main(
        [
            "--jurisdiction",
            "NC",
            "--data-type",
            "committee-documents",
            "--path",
            str(invalid_fixture),
            "--load-id",
            "nc-committee-docs-2026-04-24",
            "--load-date",
            "2026-04-24",
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "nc-committee-docs-2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 1
    assert payload["status"] == "fail"
    assert payload["scope"] == "NC_committee_documents"
    assert payload["total_rows"] == 1
    assert payload["out_of_range_rows"] == 1
    assert payload["example_rows"] == [
        {
            "record_id": payload["example_rows"][0]["record_id"],
            "field": "Received Data",
            "value": "04/30/2026",
        }
    ]


def test_validate_nc_committee_docs_flags_inverted_coverage_window() -> None:
    result = keel_gate_l6.validate_nc_rows(
        data_type="committee-documents",
        rows=[
            {
                "Committee Name": "Example Committee",
                "SBoE ID": "001-4L70LV-C-001",
                "Year": "2025",
                "Doc Type": "Disclosure Report",
                "Doc Name": "Year End Semi-Annual",
                "Amend": "N",
                "Received Image": None,
                "Received Data": "01/26/2026",
                "Start Date": "12/31/2025",
                "End Date": "07/01/2025",
                "Image": None,
                "Data": "DATA",
            }
        ],
        load_date=date(2026, 4, 24),
    )

    assert result.total_rows == 1
    assert result.out_of_range_rows == 1
    assert result.example_rows == [
        keel_gate_l6.L6ExampleRow(
            record_id=result.example_rows[0].record_id,
            field="coverage_window",
            value={"start": "12/31/2025", "end": "07/01/2025"},
        )
    ]


def test_load_domain_date_window_reads_years_back_from_keel_config_yaml(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "domains" / "campaign_finance"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "keel_config.yaml"
    config_path.write_text(
        yaml.safe_dump({"l6": {"date_window": {"years_back": 9}}}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(keel_gate_l6, "_REPO_ROOT", tmp_path)

    window = keel_gate_l6.load_domain_date_window()
    assert window.years_back == 9


def test_date_window_start_uses_config_years_back(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "domains" / "campaign_finance"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "keel_config.yaml"
    config_path.write_text(
        yaml.safe_dump({"l6": {"date_window": {"years_back": 2}}}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(keel_gate_l6, "_REPO_ROOT", tmp_path)

    start = keel_gate_l6._date_window_start(date(2026, 4, 25))
    assert start == date(2024, 1, 1)


def test_repo_owned_keel_config_yaml_declares_years_back() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "domains" / "campaign_finance" / "keel_config.yaml"
    assert config_path.is_file(), "domains/campaign_finance/keel_config.yaml must exist"

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    years_back = payload["l6"]["date_window"]["years_back"]
    assert isinstance(years_back, int)
    assert years_back >= 1
