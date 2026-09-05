from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.refresh import job_builders
from core.refresh.authority_execution_plan import AuthorityExecutionPlan
from core.refresh.authority_ledger import (
    AuthorityLedgerProof,
    main,
    validate_authority_ledger_proof,
)
from core.refresh.authority_operations_profile import canonical_sha256
from core.refresh.authority_operations_profile import expected_image_plan_proof
from core.refresh.authority_operations_profile import load_authority_operations_profile
from core.refresh.runner import RunnerParameters
from test_support.refresh_run_fixtures import refresh_job_for_tests


_PROFILE_PATH = Path(__file__).resolve().parents[2] / "infra/fly/regional_refresh_machine_profile.json"
_PROFILE = load_authority_operations_profile(_PROFILE_PATH)
_PLAN = _PROFILE.execution_plan
_STARTED = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _registry_jobs() -> list[object]:
    return [
        refresh_job_for_tests(
            key,
            jurisdiction="state/WA",
            data_source_names=(f"source for {key}",),
        )
        for key in _PLAN.scheduled.job_keys
    ]


def _canary_payload() -> dict[str, object]:
    job = _registry_jobs()[0]
    return {
        "schema_version": 1,
        "authority": {"kind": "state", "code": "WA"},
        "execution_plan_id": _PLAN.plan_id,
        "execution_plan_sha256": canonical_sha256(_PLAN.model_dump(mode="json")),
        "execution_mode": "canary",
        "observed_after": _STARTED.isoformat(),
        "observed_plan_row_count": 1,
        "runner_results": [
            {
                "job_key": job.key,
                "status": "success",
                "metadata_updates": 1,
            }
        ],
        "refresh_runs": [
            {
                "refresh_run_id": "00000000-0000-4000-8000-000000000001",
                "job_key": job.key,
                "data_source_names": list(job.data_source_names),
                "execution_origin": "operator_attended",
                "pull_status": "success",
                "metadata_updates": 1,
                "started_at": (_STARTED + timedelta(seconds=1)).isoformat(),
                "completed_at": (_STARTED + timedelta(seconds=2)).isoformat(),
            }
        ],
        "data_sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/WA",
                "name": job.data_source_names[0],
                "baseline_last_pull_at": (_STARTED - timedelta(days=1)).isoformat(),
                "post_last_pull_at": (_STARTED + timedelta(seconds=2)).isoformat(),
                "post_last_pull_status": "success",
            }
        ],
    }


def test_canary_ledger_proof_binds_exact_authority_job_origin_and_freshness() -> None:
    proof = AuthorityLedgerProof.model_validate(_canary_payload())

    validate_authority_ledger_proof(_PROFILE, proof, registry_jobs=_registry_jobs())


@pytest.mark.parametrize(
    ("path", "replacement", "error"),
    [
        (("authority", "code"), "SF", "authority mismatch"),
        (("execution_plan_id",), "regional-sf-scheduled", "plan mismatch"),
        (("execution_plan_sha256",), "0" * 64, "plan digest mismatch"),
        (("observed_plan_row_count",), 2, "row count mismatch"),
        (("refresh_runs", 0, "execution_origin"), "scheduled", "origin mismatch"),
        (("refresh_runs", 0, "job_key"), "state-wa-loans", "ledger rows"),
        (("runner_results", 0, "status"), "skipped", "ledger rows"),
        (("data_sources", 0, "jurisdiction"), "municipality/SF", "data-source ownership"),
        (
            ("data_sources", 0, "post_last_pull_at"),
            (_STARTED - timedelta(days=2)).isoformat(),
            "did not advance",
        ),
    ],
)
def test_canary_ledger_proof_fails_closed_on_identity_or_evidence_drift(
    path: tuple[str | int, ...],
    replacement: object,
    error: str,
) -> None:
    payload = deepcopy(_canary_payload())
    target: object = payload
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]

    with pytest.raises(ValueError, match=error):
        validate_authority_ledger_proof(
            _PROFILE,
            AuthorityLedgerProof.model_validate(payload),
            registry_jobs=_registry_jobs(),
        )


def test_scheduled_ledger_proof_requires_exact_order_and_all_green_or_skipped() -> None:
    jobs = _registry_jobs()
    payload = _canary_payload()
    payload["execution_mode"] = "scheduled"
    payload["runner_results"] = [{"job_key": job.key, "status": "skipped", "metadata_updates": 0} for job in jobs]
    payload["refresh_runs"] = []
    payload["observed_plan_row_count"] = 0
    payload["data_sources"] = []
    proof = AuthorityLedgerProof.model_validate(payload)
    validate_authority_ledger_proof(_PROFILE, proof, registry_jobs=jobs)

    reversed_payload = deepcopy(payload)
    reversed_payload["runner_results"] = list(reversed(reversed_payload["runner_results"]))
    with pytest.raises(ValueError, match="exact ordered job results"):
        validate_authority_ledger_proof(
            _PROFILE,
            AuthorityLedgerProof.model_validate(reversed_payload),
            registry_jobs=jobs,
        )

    red_payload = deepcopy(payload)
    red_payload["runner_results"][0]["status"] = "failed"
    with pytest.raises(ValueError, match="non-green result"):
        validate_authority_ledger_proof(
            _PROFILE,
            AuthorityLedgerProof.model_validate(red_payload),
            registry_jobs=jobs,
        )


def test_two_authority_plans_cannot_accept_each_others_ledger_proof() -> None:
    sf_plan_payload = deepcopy(_PLAN.model_dump(mode="json"))
    sf_plan_payload["authority"] = {"kind": "municipality", "code": "SF"}
    sf_plan_payload["plan_id"] = "regional-sf-scheduled"
    sf_plan_payload["contract_path"] = "infra/fly/regional_sf_refresh_machine_profile.json"
    sf_plan_payload["scheduled"]["job_keys"] = ["city-sf-transactions"]
    sf_plan_payload["canary"]["job_keys"] = ["city-sf-transactions"]
    sf_plan = AuthorityExecutionPlan.model_validate(sf_plan_payload)

    with pytest.raises(ValueError, match="authority mismatch"):
        validate_authority_ledger_proof(
            sf_plan,
            AuthorityLedgerProof.model_validate(_canary_payload()),
            registry_jobs=[
                refresh_job_for_tests(
                    "city-sf-transactions",
                    jurisdiction="municipality/SF",
                    data_source_names=("SF transactions",),
                )
            ],
        )


def test_cli_rebuilds_existing_registry_and_accepts_exact_live_profile_proof(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=RunnerParameters(),
        job_key_prefixes=(),
    )
    canary_job = next(job for job in registry_jobs if job.key == _PLAN.canary.job_keys[0])
    payload = _canary_payload()
    payload["refresh_runs"][0]["data_source_names"] = list(canary_job.data_source_names)
    payload["runner_results"][0]["metadata_updates"] = len(canary_job.data_source_names)
    payload["refresh_runs"][0]["metadata_updates"] = len(canary_job.data_source_names)
    payload["data_sources"] = [
        {
            "domain": "campaign_finance",
            "jurisdiction": "state/WA",
            "name": source_name,
            "baseline_last_pull_at": (_STARTED - timedelta(days=1)).isoformat(),
            "post_last_pull_at": (_STARTED + timedelta(seconds=2)).isoformat(),
            "post_last_pull_status": "success",
        }
        for source_name in canary_job.data_source_names
    ]
    proof_path = tmp_path / "ledger-proof.json"
    proof_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["--profile-json", str(_PROFILE_PATH), "--proof-json", str(proof_path)]) == 0
    assert capsys.readouterr().out == (
        "PASS: authority ledger proof authority=state/WA plan=regional-wa-scheduled mode=canary\n"
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regional_scheduled_observation(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    registry_jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=RunnerParameters(),
        job_key_prefixes=(),
    )
    jobs_by_key = {job.key: job for job in registry_jobs}
    selected = [jobs_by_key[key] for key in _PLAN.scheduled.job_keys]
    candidate_receipt_path = tmp_path / "candidate-receipt.json"
    candidate_build_version = {"git_sha": "1" * 40, "built_at": "2026-08-28T11:00:00Z"}
    candidate_receipt_path.write_text(
        json.dumps(
            {
                "canonical_receipt_git_sha": _PROFILE.canonical_source.receipt_git_sha,
                "canonical_source_git_sha": _PROFILE.canonical_source.source_git_sha,
                "canonical_tree_git_sha": _PROFILE.canonical_source.tree_git_sha,
                "image_proof": expected_image_plan_proof(_PROFILE, build_version=candidate_build_version),
                "machine_config_sha256": _PROFILE.machine.config_sha256,
                "produced_image_tagged_digest": "registry.fly.io/civibus-refresh:wa-r1@sha256:" + "a" * 64,
                "profile_sha256": canonical_sha256(_PROFILE.model_dump(mode="json")),
                "qualification_kind": "authority_refresh_image_candidate",
                "schema_version": 2,
                "source_git_sha": "1" * 40,
                "source_tree_git_sha": "2" * 40,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    runner_results: list[dict[str, object]] = []
    refresh_runs: list[dict[str, object]] = []
    data_sources: list[dict[str, object]] = []
    for offset, job in enumerate(selected, start=1):
        completed_at = _STARTED + timedelta(minutes=10 + offset)
        runner_results.append({"job_key": job.key, "status": "success", "metadata_updates": 1})
        refresh_runs.append(
            {
                "refresh_run_id": f"00000000-0000-4000-8000-{offset:012d}",
                "job_key": job.key,
                "data_source_names": list(job.data_source_names),
                "execution_origin": "scheduled",
                "pull_status": "success",
                "metadata_updates": 1,
                "started_at": (completed_at - timedelta(seconds=30)).isoformat(),
                "completed_at": completed_at.isoformat(),
            }
        )
        data_sources.append(
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/WA",
                "name": job.data_source_names[0],
                "baseline_last_pull_at": (_STARTED - timedelta(days=1)).isoformat(),
                "post_last_pull_at": completed_at.isoformat(),
                "post_last_pull_status": "success",
            }
        )

    machine_id = "080d391a2ed098"
    start_at = _STARTED + timedelta(minutes=5)
    terminal_at = _STARTED + timedelta(minutes=18)
    observed_at = terminal_at + timedelta(seconds=3)
    candidate = json.loads(candidate_receipt_path.read_text(encoding="utf-8"))
    raw_payloads = {
        "fly_app_status": {
            "schema_version": 1,
            "captured_at": (terminal_at + timedelta(seconds=1)).isoformat(),
            "app": _PROFILE.app,
            "machine_ids": [machine_id],
        },
        "fly_machine_status": {
            "schema_version": 1,
            "captured_at": (terminal_at + timedelta(seconds=2)).isoformat(),
            "app": _PROFILE.app,
            "machine_id": machine_id,
            "machine_name": _PROFILE.machine.name,
            "image": candidate["produced_image_tagged_digest"],
            "machine_config_sha256": _PROFILE.machine.config_sha256,
            "created_at": _STARTED.isoformat(),
            "events": [
                {
                    "type": "start",
                    "source": "scheduler",
                    "occurred_at": start_at.isoformat(),
                },
                {
                    "type": "stop",
                    "state": "stopped",
                    "exit_code": 0,
                    "occurred_at": terminal_at.isoformat(),
                },
            ],
        },
        "database_observation": {
            "schema_version": 1,
            "captured_at": (terminal_at + timedelta(seconds=3)).isoformat(),
            "machine_id": machine_id,
            "authority": {"kind": "state", "code": "WA"},
            "execution_plan_id": _PLAN.plan_id,
            "database": {"host": "civibus-db.internal", "port": 5432, "name": "civibus"},
            "runner_results": runner_results,
            "refresh_runs": refresh_runs,
            "data_sources": data_sources,
            "quiescence": {
                "running_refresh_rows": 0,
                "active_refresh_backends": 0,
                "long_idle_transactions": 0,
                "ungranted_locks": 0,
            },
        },
    }
    raw_evidence = []
    for kind, payload in raw_payloads.items():
        raw_path = tmp_path / f"{kind}.json"
        raw_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        raw_evidence.append(
            {
                "kind": kind,
                "path": str(raw_path),
                "sha256": _file_sha256(raw_path),
                "captured_at": payload["captured_at"],
            }
        )

    observation_path = tmp_path / "regional-scheduled-observation.json"
    observation_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "observed_after": _STARTED.isoformat(),
                "observed_at": observed_at.isoformat(),
                "profile_file_sha256": _file_sha256(_PROFILE_PATH),
                "candidate_receipt_file_sha256": _file_sha256(candidate_receipt_path),
                "candidate_source_git_sha": candidate["source_git_sha"],
                "candidate_tree_git_sha": candidate["source_tree_git_sha"],
                "qualified_image": candidate["produced_image_tagged_digest"],
                "app": _PROFILE.app,
                "machine_id": machine_id,
                "machine_name": _PROFILE.machine.name,
                "machine_created_at": _STARTED.isoformat(),
                "start_event": {
                    "source": "scheduler",
                    "machine_id": machine_id,
                    "occurred_at": start_at.isoformat(),
                },
                "terminal_event": {
                    "state": "stopped",
                    "exit_code": 0,
                    "machine_id": machine_id,
                    "occurred_at": terminal_at.isoformat(),
                },
                "database": {
                    "host": "civibus-db.internal",
                    "port": 5432,
                    "name": "civibus",
                },
                "runner_results": runner_results,
                "refresh_runs": refresh_runs,
                "data_sources": data_sources,
                "quiescence": {
                    "running_refresh_rows": 0,
                    "active_refresh_backends": 0,
                    "long_idle_transactions": 0,
                    "ungranted_locks": 0,
                },
                "raw_evidence": raw_evidence,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return observation_path, candidate_receipt_path, tmp_path / "proof.json", tmp_path / "receipt.json"


def _rewrite_raw_evidence(
    observation: dict[str, object],
    kind: str,
    update: Callable[[dict[str, object]], None],
) -> None:
    evidence = next(item for item in observation["raw_evidence"] if item["kind"] == kind)  # type: ignore[index]
    path = Path(evidence["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    update(payload)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    evidence["sha256"] = _file_sha256(path)


def test_regional_scheduled_observation_refuses_correctly_hashed_foreign_raw_database_identity(
    tmp_path: Path,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    database_evidence = observation["raw_evidence"][2]
    database_path = Path(database_evidence["path"])
    raw_database = json.loads(database_path.read_text(encoding="utf-8"))
    raw_database["machine_id"] = "foreign-machine"
    database_path.write_text(json.dumps(raw_database, sort_keys=True) + "\n", encoding="utf-8")
    database_evidence["sha256"] = _file_sha256(database_path)
    observation_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="raw database.*Machine identity mismatch"):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda candidate: candidate.update(unexpected="self-asserted"), "candidate receipt shape mismatch"),
        (lambda candidate: candidate.update(canonical_tree_git_sha="f" * 40), "candidate receipt identity mismatch"),
        (
            lambda candidate: candidate["image_proof"]["build_version"].update(git_sha="f" * 40),
            "candidate receipt identity mismatch",
        ),
    ],
)
def test_regional_scheduled_observation_refuses_rehashed_ambiguous_or_foreign_candidate_receipt(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    candidate = json.loads(candidate_receipt_path.read_text(encoding="utf-8"))
    mutation(candidate)
    candidate_receipt_path.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["candidate_receipt_file_sha256"] = _file_sha256(candidate_receipt_path)
    observation_path.write_text(json.dumps(observation, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )


@pytest.mark.parametrize(
    ("kind", "mutation", "error"),
    [
        ("fly_app_status", lambda raw: raw.update(app="foreign-app"), "raw app Machine identity mismatch"),
        (
            "fly_app_status",
            lambda raw: raw.update(machine_ids=["080d391a2ed098", "foreign-machine"]),
            "raw app Machine identity mismatch",
        ),
        (
            "fly_machine_status",
            lambda raw: raw.update(image="registry.fly.io/foreign@sha256:" + "f" * 64),
            "raw Fly Machine identity mismatch",
        ),
        ("fly_machine_status", lambda raw: raw["events"].reverse(), "events are ambiguous or incomplete"),
        (
            "fly_machine_status",
            lambda raw: raw["events"].append(deepcopy(raw["events"][-1])),
            "events are ambiguous or incomplete",
        ),
        (
            "database_observation",
            lambda raw: raw["quiescence"].update(ungranted_locks=1),
            "not valid owner-format evidence",
        ),
        ("database_observation", lambda raw: raw.update(unexpected="self-asserted"), "not valid owner-format evidence"),
    ],
)
def test_regional_scheduled_observation_refuses_correctly_hashed_foreign_or_malformed_raw_evidence(
    tmp_path: Path,
    kind: str,
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    _rewrite_raw_evidence(observation, kind, mutation)
    observation_path.write_text(json.dumps(observation, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
    assert not proof_path.exists()
    assert not receipt_path.exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda database: [row.update(execution_origin="operator_attended") for row in database["refresh_runs"]],
            "execution-origin mismatch",
        ),
        (
            lambda database: database["refresh_runs"][1].update(
                refresh_run_id=database["refresh_runs"][0]["refresh_run_id"]
            ),
            "duplicate or replayed refresh attempts",
        ),
        (
            lambda database: (
                database["runner_results"].reverse(),
                database["refresh_runs"].reverse(),
                database["data_sources"].reverse(),
            ),
            "exact ordered job results",
        ),
        (
            lambda database: (
                database["runner_results"].pop(),
                database["refresh_runs"].pop(),
                database["data_sources"].pop(),
            ),
            "exact ordered job results",
        ),
        (
            lambda database: database["data_sources"][0].update(
                post_last_pull_at=database["data_sources"][0]["baseline_last_pull_at"]
            ),
            "source clock is not current|freshness did not advance",
        ),
        (
            lambda database: database["data_sources"][0].update(
                post_last_pull_at=(_STARTED + timedelta(minutes=19)).isoformat()
            ),
            "source clock is not current",
        ),
    ],
)
def test_regional_scheduled_observation_refuses_aligned_manual_replayed_partial_or_stale_raw_evidence(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
    error: str,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    database_reference = next(row for row in observation["raw_evidence"] if row["kind"] == "database_observation")
    database_path = Path(database_reference["path"])
    database = json.loads(database_path.read_text(encoding="utf-8"))
    mutation(database)
    for key in ("runner_results", "refresh_runs", "data_sources", "quiescence"):
        observation[key] = deepcopy(database[key])
    database_path.write_text(json.dumps(database, sort_keys=True) + "\n", encoding="utf-8")
    database_reference["sha256"] = _file_sha256(database_path)
    observation_path.write_text(json.dumps(observation, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
    assert not proof_path.exists()
    assert not receipt_path.exists()


def test_cli_builds_exact_regional_scheduled_observation_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)

    assert (
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
        == 0
    )

    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert [result["job_key"] for result in proof["runner_results"]] == list(_PLAN.scheduled.job_keys)
    assert {result["status"] for result in proof["runner_results"]} == {"success"}
    assert [row["execution_origin"] for row in proof["refresh_runs"]] == ["scheduled"] * 4
    assert receipt["profile_file_sha256"] == _file_sha256(_PROFILE_PATH)
    assert receipt["candidate_receipt_file_sha256"] == _file_sha256(candidate_receipt_path)
    assert receipt["authority_ledger_proof_sha256"] == canonical_sha256(proof)
    assert receipt["machine_id"] == "080d391a2ed098"
    assert [source["name"] for source in receipt["data_sources"]] == [
        "WA PDC Contributions",
        "WA PDC Expenditures",
        "WA PDC Independent Expenditures",
        "WA PDC Loans",
    ]
    assert stat.S_IMODE(proof_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert capsys.readouterr().out == (
        "PASS: regional scheduled observation "
        "authority=state/WA plan=regional-wa-scheduled machine=080d391a2ed098 results=4\n"
    )

    proof_sha256 = _file_sha256(proof_path)
    receipt_sha256 = _file_sha256(receipt_path)
    with pytest.raises(ValueError, match="proof output path already exists"):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
    assert _file_sha256(proof_path) == proof_sha256
    assert _file_sha256(receipt_path) == receipt_sha256


def test_cli_derives_scheduled_observation_from_exact_three_raw_owner_formats(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hand_observation_path, candidate_receipt_path, _, _ = _regional_scheduled_observation(tmp_path)
    hand_observation = json.loads(hand_observation_path.read_text(encoding="utf-8"))
    raw_paths = {reference["kind"]: reference["path"] for reference in hand_observation["raw_evidence"]}
    observation_path = tmp_path / "derived-observation.json"
    proof_path = tmp_path / "derived-proof.json"
    receipt_path = tmp_path / "derived-receipt.json"

    assert (
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--raw-fly-app-status-json",
                raw_paths["fly_app_status"],
                "--raw-fly-machine-status-json",
                raw_paths["fly_machine_status"],
                "--raw-database-observation-json",
                raw_paths["database_observation"],
                "--observation-output-json",
                str(observation_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
        == 0
    )

    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    machine = json.loads(Path(raw_paths["fly_machine_status"]).read_text(encoding="utf-8"))
    database = json.loads(Path(raw_paths["database_observation"]).read_text(encoding="utf-8"))
    assert observation["machine_id"] == machine["machine_id"]
    assert observation["start_event"]["source"] == machine["events"][0]["source"]
    assert observation["start_event"]["machine_id"] == machine["machine_id"]
    assert datetime.fromisoformat(observation["start_event"]["occurred_at"].replace("Z", "+00:00")) == (
        datetime.fromisoformat(machine["events"][0]["occurred_at"].replace("Z", "+00:00"))
    )
    assert observation["terminal_event"]["state"] == machine["events"][1]["state"]
    assert observation["terminal_event"]["exit_code"] == machine["events"][1]["exit_code"]
    assert observation["terminal_event"]["machine_id"] == machine["machine_id"]
    assert datetime.fromisoformat(observation["terminal_event"]["occurred_at"].replace("Z", "+00:00")) == (
        datetime.fromisoformat(machine["events"][1]["occurred_at"].replace("Z", "+00:00"))
    )
    assert observation["runner_results"] == database["runner_results"]
    assert [row["refresh_run_id"] for row in observation["refresh_runs"]] == [
        row["refresh_run_id"] for row in database["refresh_runs"]
    ]
    assert [row["job_key"] for row in observation["refresh_runs"]] == [
        row["job_key"] for row in database["refresh_runs"]
    ]
    assert [row["name"] for row in observation["data_sources"]] == [row["name"] for row in database["data_sources"]]
    assert observation["quiescence"] == database["quiescence"]
    assert [reference["kind"] for reference in observation["raw_evidence"]] == [
        "fly_app_status",
        "fly_machine_status",
        "database_observation",
    ]
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(proof_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert "PASS: derived regional scheduled observation" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("path", "replacement", "error"),
    [
        (("profile_file_sha256",), "0" * 64, "profile digest mismatch"),
        (("candidate_receipt_file_sha256",), "0" * 64, "candidate receipt digest mismatch"),
        (("app",), "foreign-regional-refresh", "app or Machine identity mismatch"),
        (("machine_name",), "foreign-machine", "app or Machine identity mismatch"),
        (("machine_id",), "", "Machine id must not be empty"),
        (("terminal_event", "machine_id"), "foreign-machine", "event Machine identity mismatch"),
        (("start_event", "source"), "user", "scheduler.*host"),
        (("start_event", "occurred_at"), (_STARTED - timedelta(seconds=1)).isoformat(), "event window"),
        (("terminal_event", "state"), "started", "stopped"),
        (("terminal_event", "exit_code"), 1, "Input should be 0"),
        (("database", "name"), "foreign", "database identity mismatch"),
        (("runner_results", 0, "status"), "failed", "non-green result"),
        (("refresh_runs", 0, "execution_origin"), "operator_attended", "execution-origin mismatch"),
        (("data_sources", 0, "name"), "foreign source", "exact ordered registry sources"),
        (("data_sources", 0, "jurisdiction"), "state/OR", "source ownership mismatch"),
        (("data_sources", 0, "post_last_pull_at"), _STARTED.isoformat(), "source clock is not current"),
        (("quiescence", "running_refresh_rows"), 1, "Input should be 0"),
        (("raw_evidence", 0, "kind"), "database_observation", "exact ordered raw"),
        (("raw_evidence", 0, "sha256"), "0" * 64, "fly_app_status digest mismatch"),
        (("raw_evidence", 0, "captured_at"), _STARTED.isoformat(), "outside the terminal window"),
        (
            ("observed_at",),
            (_STARTED + timedelta(minutes=18, seconds=4)).isoformat(),
            "observation time is not derived",
        ),
    ],
)
def test_regional_scheduled_observation_refuses_identity_execution_freshness_or_raw_evidence_drift(
    tmp_path: Path,
    path: tuple[str | int, ...],
    replacement: object,
    error: str,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    payload = json.loads(observation_path.read_text(encoding="utf-8"))
    target: object = payload
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    if path[0] in {"runner_results", "refresh_runs", "data_sources"}:
        _rewrite_raw_evidence(
            payload,
            "database_observation",
            lambda raw: raw.__setitem__(path[0], payload[path[0]]),
        )
    observation_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(observation_path),
                "--candidate-receipt-json",
                str(candidate_receipt_path),
                "--proof-output-json",
                str(proof_path),
                "--receipt-output-json",
                str(receipt_path),
            ]
        )
    assert not proof_path.exists()
    assert not receipt_path.exists()


def test_regional_scheduled_observation_requires_all_four_successes_and_accepts_host_origin(
    tmp_path: Path,
) -> None:
    observation_path, candidate_receipt_path, proof_path, receipt_path = _regional_scheduled_observation(tmp_path)
    payload = json.loads(observation_path.read_text(encoding="utf-8"))
    payload["runner_results"] = [
        {**result, "status": "skipped", "metadata_updates": 0} for result in payload["runner_results"]
    ]
    payload["refresh_runs"] = []
    _rewrite_raw_evidence(
        payload,
        "database_observation",
        lambda raw: raw.update(
            runner_results=payload["runner_results"],
            refresh_runs=payload["refresh_runs"],
        ),
    )
    observation_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    args = [
        "--profile-json",
        str(_PROFILE_PATH),
        "--observation-json",
        str(observation_path),
        "--candidate-receipt-json",
        str(candidate_receipt_path),
        "--proof-output-json",
        str(proof_path),
        "--receipt-output-json",
        str(receipt_path),
    ]
    with pytest.raises(ValueError, match="requires every plan result to succeed"):
        main(args)

    host_root = tmp_path / "host"
    host_root.mkdir()
    payload = json.loads(_regional_scheduled_observation(host_root)[0].read_text(encoding="utf-8"))
    host_observation = host_root / "regional-scheduled-observation.json"
    payload["start_event"]["source"] = "host"
    _rewrite_raw_evidence(
        payload,
        "fly_machine_status",
        lambda raw: raw["events"][0].__setitem__("source", "host"),
    )
    host_observation.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert (
        main(
            [
                "--profile-json",
                str(_PROFILE_PATH),
                "--observation-json",
                str(host_observation),
                "--candidate-receipt-json",
                str(host_root / "candidate-receipt.json"),
                "--proof-output-json",
                str(host_root / "proof.json"),
                "--receipt-output-json",
                str(host_root / "receipt.json"),
            ]
        )
        == 0
    )
