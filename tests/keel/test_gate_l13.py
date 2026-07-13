from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema.validators import validator_for

import core.keel_gate_l13 as keel_gate_l13


REPO_ROOT = Path(__file__).resolve().parents[2]
L13_SCHEMA_PATH = REPO_ROOT / "evidence_schemas" / "L13.json"
EXPECTED_OWNER_FILES = {
    ".github/workflows/deploy.yml",
    "infra/fly/api.fly.toml",
    "infra/fly/web.fly.toml",
    "infra/fly/caddy.fly.toml",
}
EXPECTED_FLY_DEPLOY_COMMANDS = [
    "flyctl deploy -c infra/fly/api.fly.toml --remote-only",
    'flyctl deploy web -c "$GITHUB_WORKSPACE/infra/fly/web.fly.toml" --remote-only',
    "flyctl deploy -c infra/fly/caddy.fly.toml --remote-only",
]


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_live_snapshot() -> dict[str, object]:
    return {
        "workflow": {
            "deploy_if": "github.repository == 'gridl-hq/civibus'",
            "deploy_env": {
                "FLY_API_TOKEN": "fly-secret-token",
                "PROD_SMOKE_BASE_URL": "${{ vars.PROD_SMOKE_BASE_URL }}",
            },
            "fly_deploy_commands": EXPECTED_FLY_DEPLOY_COMMANDS,
        },
        "fly_apps": {
            "api": "civibus-api",
            "web": "civibus-web",
            "caddy": "civibus-caddy",
        },
    }


def test_extract_repo_contract_locks_fly_deploy_owner_files() -> None:
    contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)

    assert set(contract["owner_files"]) == EXPECTED_OWNER_FILES
    assert contract["non_secret"]["workflow.deploy_if"] == "github.repository == 'gridl-hq/civibus'"
    assert contract["non_secret"]["workflow.deploy_env.PROD_SMOKE_BASE_URL"] == "${{ vars.PROD_SMOKE_BASE_URL }}"
    assert contract["non_secret"]["workflow.fly_deploy_commands"] == sorted(EXPECTED_FLY_DEPLOY_COMMANDS)
    assert contract["non_secret"]["fly_apps.api"] == "civibus-api"
    assert contract["non_secret"]["fly_apps.web"] == "civibus-web"
    assert contract["non_secret"]["fly_apps.caddy"] == "civibus-caddy"
    assert contract["secret_presence"]["workflow.deploy_env.FLY_API_TOKEN"] is True


def test_normalize_live_snapshot_hashes_secret_values() -> None:
    raw_snapshot = _sample_live_snapshot()
    normalized = keel_gate_l13.normalize_live_snapshot(raw_snapshot)
    serialized = json.dumps(normalized, sort_keys=True)

    assert "fly-secret-token" not in serialized

    secret_fingerprint = normalized["secret_fingerprints"]["workflow.deploy_env.FLY_API_TOKEN"]
    assert secret_fingerprint["present"] is True
    assert str(secret_fingerprint["fingerprint"]).startswith("sha256:")
    assert normalized["non_secret"]["fly_apps.api"] == "civibus-api"


def test_evaluate_contract_drift_fails_on_outside_diff_surface_paths() -> None:
    repo_contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)
    raw_snapshot = _sample_live_snapshot()
    raw_snapshot["workflow"]["deploy_env"]["UNTRACKED_RUNTIME_KEY"] = "sensitive-runtime-value"  # type: ignore[index]

    evaluation = keel_gate_l13.evaluate_contract_drift(
        repo_contract=repo_contract,
        normalized_live_snapshot=keel_gate_l13.normalize_live_snapshot(raw_snapshot),
        deploy_id="outside-surface",
        debt_entries=[],
        produced_at=datetime(2026, 7, 7, 12, 30, tzinfo=UTC),
    )

    assert evaluation.status == "fail"
    outside_surface_entries = [
        entry for entry in evaluation.diff_entries if entry["drift_type"] == "outside_diff_surface"
    ]
    assert outside_surface_entries
    assert outside_surface_entries[0]["path"] == "workflow.deploy_env.UNTRACKED_RUNTIME_KEY"
    assert outside_surface_entries[0]["live_value"] == "<redacted-outside-surface>"
    assert "sensitive-runtime-value" not in json.dumps(evaluation.diff_entries, sort_keys=True)


def test_evaluate_contract_drift_flags_expired_and_unmatched_debt_entries(tmp_path: Path) -> None:
    repo_contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)
    normalized_live_snapshot = keel_gate_l13.normalize_live_snapshot(_sample_live_snapshot())

    debt_file_path = tmp_path / "deploy_hot_patch_debt.yaml"
    debt_file_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "expired-hot-patch",
                        "deploy_id": "test-deploy",
                        "path": "fly_apps.api",
                        "expected_live_value": "civibus-api-hotfix",
                        "reason": "expired allowlist should fail",
                        "expires_at_utc": "2026-01-01T00:00:00Z",
                    },
                    {
                        "entry_id": "active-but-unmatched",
                        "deploy_id": "test-deploy",
                        "path": "workflow.deploy_if",
                        "expected_live_value": "github.repository == 'gridl-hq/hotfix'",
                        "reason": "unmatched allowlist should fail",
                        "expires_at_utc": "2026-08-01T00:00:00Z",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    debt_entries = keel_gate_l13.load_deploy_hot_patch_debt(debt_file_path)
    evaluation = keel_gate_l13.evaluate_contract_drift(
        repo_contract=repo_contract,
        normalized_live_snapshot=normalized_live_snapshot,
        deploy_id="test-deploy",
        debt_entries=debt_entries,
        produced_at=datetime(2026, 7, 7, 12, 30, tzinfo=UTC),
    )

    assert evaluation.status == "fail"
    assert "expired-hot-patch" in evaluation.expired_debt_ids
    assert "active-but-unmatched" in evaluation.unmatched_debt_ids


def test_write_l13_evidence_emits_expected_diff_summary_shape(tmp_path: Path) -> None:
    repo_contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)
    live_snapshot = _sample_live_snapshot()
    live_snapshot["fly_apps"]["api"] = "civibus-api-hotfix"  # type: ignore[index]

    evaluation = keel_gate_l13.evaluate_contract_drift(
        repo_contract=repo_contract,
        normalized_live_snapshot=keel_gate_l13.normalize_live_snapshot(live_snapshot),
        deploy_id="test-deploy",
        debt_entries=[],
        produced_at=datetime(2026, 7, 7, 13, 0, tzinfo=UTC),
    )
    evidence_path = keel_gate_l13.write_l13_evidence(
        evaluation=evaluation,
        deploy_id="test-deploy",
        repo_sha="abc12345",
        produced_at=datetime(2026, 7, 7, 13, 0, tzinfo=UTC),
        evidence_root=tmp_path,
    )
    payload = _read_json(evidence_path)

    assert evidence_path.name == "test-deploy.json"
    assert payload["layer"] == "L13"
    assert payload["scope"] == "global"
    assert payload["status"] == "fail"
    assert payload["diff_summary"]["unexpected_drift"] == 1
    assert payload["diff_summary"]["allowed_drift"] == 0
    assert payload["diff_summary"]["total_drift"] == 1
    assert payload["reconciliation"]["test-deploy"]["unexpected_drift_count"] == 1


def test_schema_canary_validates_l13_schema_and_generated_payload(tmp_path: Path) -> None:
    schema = json.loads(L13_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    repo_contract = keel_gate_l13.extract_repo_contract(repo_root=REPO_ROOT)
    evaluation = keel_gate_l13.evaluate_contract_drift(
        repo_contract=repo_contract,
        normalized_live_snapshot=keel_gate_l13.normalize_live_snapshot(_sample_live_snapshot()),
        deploy_id="schema-canary",
        debt_entries=[],
        produced_at=datetime(2026, 7, 7, 13, 15, tzinfo=UTC),
    )
    evidence_path = keel_gate_l13.write_l13_evidence(
        evaluation=evaluation,
        deploy_id="schema-canary",
        repo_sha="abc12345",
        produced_at=datetime(2026, 7, 7, 13, 15, tzinfo=UTC),
        evidence_root=tmp_path,
    )
    payload = _read_json(evidence_path)

    assert list(validator.iter_errors(payload)) == []


def test_main_writes_evidence_without_live_fly_probe(monkeypatch, tmp_path: Path) -> None:
    live_snapshot_path = tmp_path / "live_snapshot.json"
    live_snapshot_path.write_text(json.dumps(_sample_live_snapshot(), indent=2) + "\n", encoding="utf-8")
    debt_file_path = tmp_path / "deploy_hot_patch_debt.yaml"
    debt_file_path.write_text("schema_version: 1\nentries: []\n", encoding="utf-8")

    monkeypatch.setattr(keel_gate_l13, "_repo_sha", lambda repo_root=None: "abc12345")
    monkeypatch.setattr(keel_gate_l13, "_utc_now", lambda: datetime(2026, 7, 7, 14, 0, tzinfo=UTC))

    exit_code = keel_gate_l13.main(
        [
            "--repo-root",
            str(REPO_ROOT),
            "--live-snapshot-path",
            str(live_snapshot_path),
            "--debt-file",
            str(debt_file_path),
            "--evidence-root",
            str(tmp_path),
            "--deploy-id",
            "cli-fixture",
        ]
    )
    payload = _read_json(tmp_path / "cli-fixture.json")

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["diff_summary"]["total_drift"] == 0


def test_main_uses_cli_repo_root_for_repo_sha(monkeypatch, tmp_path: Path) -> None:
    alt_repo_root = tmp_path / "alt_repo"
    live_snapshot_path = tmp_path / "live_snapshot.json"
    debt_file_path = tmp_path / "deploy_hot_patch_debt.yaml"
    expected_repo_sha = "feedbeef"
    live_snapshot_path.write_text(json.dumps(_sample_live_snapshot(), indent=2) + "\n", encoding="utf-8")
    debt_file_path.write_text("schema_version: 1\nentries: []\n", encoding="utf-8")

    for owner_path in EXPECTED_OWNER_FILES:
        source_path = REPO_ROOT / owner_path
        destination_path = alt_repo_root / owner_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _fake_check_output(command: list[str], cwd: Path, text: bool) -> str:
        assert command == ["git", "rev-parse", "--short=8", "HEAD"]
        assert cwd == alt_repo_root
        assert text is True
        return f"{expected_repo_sha}\n"

    monkeypatch.setattr(keel_gate_l13.subprocess, "check_output", _fake_check_output)
    monkeypatch.setattr(keel_gate_l13, "_utc_now", lambda: datetime(2026, 7, 7, 14, 0, tzinfo=UTC))

    exit_code = keel_gate_l13.main(
        [
            "--repo-root",
            str(alt_repo_root),
            "--live-snapshot-path",
            str(live_snapshot_path),
            "--debt-file",
            str(debt_file_path),
            "--evidence-root",
            str(tmp_path),
            "--deploy-id",
            "cli-repo-root",
        ]
    )
    payload = _read_json(tmp_path / "cli-repo-root.json")

    assert exit_code == 0
    assert payload["repo_sha"] == expected_repo_sha
