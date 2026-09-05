from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from core.refresh import runner
from core.refresh.authority_execution_plan import (
    AuthorityExecutionPlan,
    expected_runner_command,
    load_authority_execution_plan,
    select_execution_plan_jobs,
    validate_disjoint_execution_plans,
)
from core.refresh.runner import RefreshJob


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WA_PROFILE = _REPO_ROOT / "infra/fly/regional_refresh_machine_profile.json"
_WA_JOB_KEYS = (
    "state-wa-contributions",
    "state-wa-expenditures",
    "state-wa-independent_expenditures",
    "state-wa-loans",
)


def _job(key: str, jurisdiction: str) -> RefreshJob:
    return RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        cadence="daily",
        data_source_names=(f"source for {key}",),
        run_callable=lambda: None,
    )


def _synthetic_plan(*, kind: str, code: str, plan_id: str, job_key: str) -> AuthorityExecutionPlan:
    return AuthorityExecutionPlan.model_validate(
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "contract_path": f"infra/fly/{plan_id}.json",
            "authority": {"kind": kind, "code": code},
            "scheduled": {
                "execution_origin": "scheduled",
                "job_keys": [job_key],
                "schedule": "daily",
                "stop_on_failure": False,
            },
            "canary": {
                "execution_origin": "operator_attended",
                "job_keys": [job_key],
                "schedule": None,
                "stop_on_failure": True,
            },
            "concurrency": {
                "max_parallel_jobs": 1,
                "same_host_lock": "exact_authority_and_job_key_flock",
                "cross_host_lock": "exact_authority_and_job_key_postgres_advisory_lock",
            },
            "cadence_clock": {
                "scheduler": "machine_schedule",
                "job_due": "refresh_history_or_data_source_per_job",
                "force_allowed": False,
            },
        }
    )


def test_live_authority_plan_selects_exact_ordered_jobs_from_existing_registry() -> None:
    plan = load_authority_execution_plan(_WA_PROFILE)
    registry_jobs = [_job(key, "state/WA") for key in reversed(_WA_JOB_KEYS)]

    selected = select_execution_plan_jobs(registry_jobs, plan, mode="scheduled")

    assert tuple(job.key for job in selected) == _WA_JOB_KEYS
    assert plan.authority.operational_scope == "state/WA"
    assert plan.ownership_lock_key == "authority-plan:state/WA"


def test_live_plan_makes_scheduled_canary_concurrency_and_cadence_semantics_explicit() -> None:
    plan = load_authority_execution_plan(_WA_PROFILE)

    assert plan.scheduled.job_keys == _WA_JOB_KEYS
    assert plan.scheduled.execution_origin == "scheduled"
    assert plan.scheduled.stop_on_failure is False
    assert plan.scheduled.schedule == "daily"
    assert plan.canary.job_keys == ("state-wa-contributions",)
    assert plan.canary.execution_origin == "operator_attended"
    assert plan.canary.stop_on_failure is True
    assert plan.canary.schedule is None
    assert plan.concurrency.max_parallel_jobs == 1
    assert plan.cadence_clock.force_allowed is False
    assert expected_runner_command(plan, mode="scheduled") == (
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        "infra/fly/regional_refresh_machine_profile.json",
        "--execution-mode",
        "scheduled",
        "--execution-origin",
        "scheduled",
    )
    assert expected_runner_command(plan, mode="canary")[-1] == "operator_attended"


@pytest.mark.parametrize(
    ("jobs", "match"),
    (
        ([_job(_WA_JOB_KEYS[0], "state/WA")], "missing registered job keys"),
        ([_job(key, "state/OR") for key in _WA_JOB_KEYS], "crosses authority ownership"),
        (
            [_job(key, "state/WA") for key in _WA_JOB_KEYS] + [_job(_WA_JOB_KEYS[0], "state/WA")],
            "duplicate registry job keys",
        ),
    ),
)
def test_authority_plan_fails_closed_for_incomplete_cross_authority_or_ambiguous_registry(
    jobs: list[RefreshJob],
    match: str,
) -> None:
    plan = load_authority_execution_plan(_WA_PROFILE)

    with pytest.raises(ValueError, match=match):
        select_execution_plan_jobs(jobs, plan, mode="scheduled")


def test_two_authority_plans_cannot_share_job_or_authority_ownership() -> None:
    wa_plan = _synthetic_plan(
        kind="state",
        code="WA",
        plan_id="synthetic-wa",
        job_key="state-wa-contributions",
    )
    sf_plan = _synthetic_plan(
        kind="municipality",
        code="SF",
        plan_id="synthetic-sf",
        job_key="city-sf-transactions",
    )

    validate_disjoint_execution_plans((wa_plan, sf_plan))
    assert (
        select_execution_plan_jobs(
            [_job("state-wa-contributions", "state/WA"), _job("city-sf-transactions", "municipality/SF")],
            sf_plan,
            mode="scheduled",
        )[0].key
        == "city-sf-transactions"
    )

    shared_job_payload = deepcopy(sf_plan.model_dump(mode="json"))
    shared_job_payload["scheduled"]["job_keys"] = ["state-wa-contributions"]
    shared_job_payload["canary"]["job_keys"] = ["state-wa-contributions"]
    with pytest.raises(ValueError, match="share refresh job ownership"):
        validate_disjoint_execution_plans((wa_plan, AuthorityExecutionPlan.model_validate(shared_job_payload)))

    shared_authority_payload = deepcopy(sf_plan.model_dump(mode="json"))
    shared_authority_payload["authority"] = {"kind": "state", "code": "WA"}
    with pytest.raises(ValueError, match="share authority ownership"):
        validate_disjoint_execution_plans((wa_plan, AuthorityExecutionPlan.model_validate(shared_authority_payload)))


def test_scheduled_origin_and_canary_validation_are_plan_driven_and_fail_closed() -> None:
    plan = load_authority_execution_plan(_WA_PROFILE)
    scheduled_jobs = [_job(key, "state/WA") for key in _WA_JOB_KEYS]
    canary_jobs = scheduled_jobs[:1]

    runner._validate_execution_origin_for_jobs(
        "scheduled",
        scheduled_jobs,
        execution_plan=plan,
        execution_mode="scheduled",
        require_complete_mode_plan=True,
    )
    runner._validate_execution_origin_for_jobs(
        "operator_attended",
        canary_jobs,
        execution_plan=plan,
        execution_mode="canary",
    )

    with pytest.raises(ValueError, match="requires an authority execution plan"):
        runner._validate_execution_origin_for_jobs("scheduled", scheduled_jobs)
    with pytest.raises(ValueError, match="exact ordered job set"):
        runner._validate_execution_origin_for_jobs(
            "scheduled",
            scheduled_jobs[:-1],
            execution_plan=plan,
            execution_mode="scheduled",
        )
    with pytest.raises(ValueError, match="origin mismatch"):
        runner._validate_execution_origin_for_jobs(
            "operator_attended",
            scheduled_jobs,
            execution_plan=plan,
            execution_mode="scheduled",
            require_complete_mode_plan=True,
        )
    with pytest.raises(ValueError, match="does not allow dry-run or forced"):
        runner._validate_execution_origin_for_jobs(
            "operator_attended",
            canary_jobs,
            force=True,
            execution_plan=plan,
            execution_mode="canary",
        )


def test_planned_lock_set_binds_exact_authority_and_jobs_without_cross_authority_sharing() -> None:
    wa_plan = load_authority_execution_plan(_WA_PROFILE)
    wa_jobs = [_job(key, "state/WA") for key in _WA_JOB_KEYS]
    sf_plan = _synthetic_plan(
        kind="municipality",
        code="SF",
        plan_id="synthetic-sf-locks",
        job_key="city-sf-transactions",
    )

    wa_lock_keys = runner._runner_lock_keys_for_jobs(
        wa_jobs,
        authority_ownership_lock_key=wa_plan.ownership_lock_key,
    )
    sf_lock_keys = runner._runner_lock_keys_for_jobs(
        [_job("city-sf-transactions", "municipality/SF")],
        authority_ownership_lock_key=sf_plan.ownership_lock_key,
    )

    assert wa_plan.ownership_lock_key in wa_lock_keys
    assert sf_plan.ownership_lock_key in sf_lock_keys
    assert set(wa_lock_keys).isdisjoint(sf_lock_keys)


def test_scheduled_cli_refuses_legacy_prefix_shape_before_building_or_connecting() -> None:
    with pytest.raises(SystemExit, match="2"):
        runner.main(
            [
                "--scope",
                "all",
                "--job-key-prefix",
                "state-wa-",
                "--execution-origin",
                "scheduled",
            ]
        )
