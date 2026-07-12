"""Run bounded portal exploration loops and persist checkpointed run artifacts."""

import json
from pathlib import Path
import re

from domains.campaign_finance.jurisdictions.portal_explorer.capture import (
    attach_network_capture,
    capture_page_state,
)
from domains.campaign_finance.jurisdictions.portal_explorer.contract import (
    PortalExplorerProposalInput,
    PortalExplorerProposalResult,
    PortalExplorerRequest,
    PortalExplorerRunResult,
    PortalExplorerRunSummary,
    PortalExplorerStepRecord,
)
from domains.campaign_finance.jurisdictions.portal_explorer.proposer import (
    propose_next_action,
    validate_action_against_page_state,
)
from domains.campaign_finance.jurisdictions.protected_portal import (
    ProtectedPortalBrowserSettings,
    launch_browser_session,
    open_playwright,
)

_RUN_ARTIFACT_ROOT = Path("docs/reference/research/portal_contracts/runs")
_RUN_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9_]+")


def run(request: PortalExplorerRequest) -> PortalExplorerRunResult:
    """Run a bounded portal exploration loop and persist checkpoint artifacts."""
    validated_request = PortalExplorerRequest.model_validate(request.model_dump(mode="json"))
    checkpoint_path = _checkpoint_path_for_request(validated_request)
    steps: list[PortalExplorerStepRecord] = []

    try:
        with open_playwright("portal explorer run") as playwright:
            settings = ProtectedPortalBrowserSettings(
                channel="chrome",
                headless=True,
                accept_downloads=True,
                user_data_dir=None,
            )
            with launch_browser_session(playwright, settings) as session:
                page = session.context.new_page()
                recorder = attach_network_capture(page, validated_request.capture_config)
                page.goto(validated_request.entry_url)

                for step_index in range(validated_request.max_steps):
                    page_state = capture_page_state(page, recorder, validated_request.capture_config)
                    proposal_input = PortalExplorerProposalInput(
                        goal=validated_request.goal,
                        page_state=page_state,
                        completed_steps=steps,
                    )
                    proposal_result = propose_next_action(proposal_input)
                    if proposal_result.status == "invalid":
                        return _terminal_failure_result(
                            request=validated_request,
                            steps=steps,
                            checkpoint_path=checkpoint_path,
                            step_index=step_index,
                            reason=proposal_result.reason or "Proposer returned invalid result",
                        )

                    validated_proposal = _validate_proposal_or_fail(
                        request=validated_request,
                        steps=steps,
                        checkpoint_path=checkpoint_path,
                        step_index=step_index,
                        proposal_result=proposal_result,
                        page_state=page_state,
                    )
                    if isinstance(validated_proposal, PortalExplorerRunResult):
                        return validated_proposal

                    action = validated_proposal
                    if action.action_type == "done":
                        steps.append(
                            PortalExplorerStepRecord(
                                step_index=step_index,
                                page_url=page_state.url,
                                action=action,
                            )
                        )
                        terminal = _build_result(
                            request=validated_request,
                            steps=steps,
                            checkpoint_path=checkpoint_path,
                            summary=PortalExplorerRunSummary(
                                status="done",
                                message="Proposer indicated exploration is complete",
                                steps_completed=len(steps),
                            ),
                        )
                        _write_checkpoint(terminal)
                        return terminal

                    try:
                        _execute_action(page, action)
                    except Exception as error:  # noqa: BLE001
                        return _terminal_failure_result(
                            request=validated_request,
                            steps=steps,
                            checkpoint_path=checkpoint_path,
                            step_index=step_index,
                            reason=f"Action execution failed: {error}",
                        )

                    steps.append(
                        PortalExplorerStepRecord(
                            step_index=step_index,
                            page_url=page_state.url,
                            action=action,
                        )
                    )
                    progress = _build_result(
                        request=validated_request,
                        steps=steps,
                        checkpoint_path=checkpoint_path,
                        summary=PortalExplorerRunSummary(
                            status="running",
                            message="Explorer loop in progress",
                            steps_completed=len(steps),
                        ),
                    )
                    _write_checkpoint(progress)
    except Exception as error:  # noqa: BLE001
        return _terminal_failure_result(
            request=validated_request,
            steps=steps,
            checkpoint_path=checkpoint_path,
            step_index=len(steps),
            reason=f"Explorer runtime failed: {error}",
        )

    exhausted = _build_result(
        request=validated_request,
        steps=steps,
        checkpoint_path=checkpoint_path,
        summary=PortalExplorerRunSummary(
            status="exhausted",
            message=f"Reached max_steps={validated_request.max_steps} without terminal done action",
            steps_completed=len(steps),
        ),
    )
    _write_checkpoint(exhausted)
    return exhausted


def _validate_proposal_or_fail(
    *,
    request: PortalExplorerRequest,
    steps: list[PortalExplorerStepRecord],
    checkpoint_path: Path,
    step_index: int,
    proposal_result: PortalExplorerProposalResult,
    page_state: object,
):
    action = proposal_result.action
    if action is None:
        return _terminal_failure_result(
            request=request,
            steps=steps,
            checkpoint_path=checkpoint_path,
            step_index=step_index,
            reason="Proposer returned proposed status without action payload",
        )

    validation = validate_action_against_page_state(action, page_state)
    if validation.status == "invalid":
        return _terminal_failure_result(
            request=request,
            steps=steps,
            checkpoint_path=checkpoint_path,
            step_index=step_index,
            reason=validation.reason or "Action selector validation failed",
        )

    assert validation.action is not None
    return validation.action


def _terminal_failure_result(
    *,
    request: PortalExplorerRequest,
    steps: list[PortalExplorerStepRecord],
    checkpoint_path: Path,
    step_index: int,
    reason: str,
) -> PortalExplorerRunResult:
    failed = _build_result(
        request=request,
        steps=steps,
        checkpoint_path=checkpoint_path,
        summary=PortalExplorerRunSummary(
            status="failed",
            message="Explorer loop failed",
            steps_completed=len(steps),
            failure_step_index=step_index,
            failure_reason=reason,
        ),
    )
    _write_checkpoint(failed)
    return failed


def _execute_action(page: object, action: object) -> None:
    if action.action_type == "click":
        assert action.selector is not None
        page.click(action.selector)  # type: ignore[union-attr]
        return
    if action.action_type == "fill":
        assert action.selector is not None
        assert action.value is not None
        page.fill(action.selector, action.value)  # type: ignore[union-attr]
        return
    raise ValueError(f"Unsupported executable action_type={action.action_type!r}")


def _build_result(
    *,
    request: PortalExplorerRequest,
    steps: list[PortalExplorerStepRecord],
    checkpoint_path: Path,
    summary: PortalExplorerRunSummary,
) -> PortalExplorerRunResult:
    return PortalExplorerRunResult(
        request=request,
        summary=summary,
        steps=list(steps),
        checkpoint_path=str(checkpoint_path),
    )


def _checkpoint_path_for_request(request: PortalExplorerRequest) -> Path:
    _RUN_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    run_label = request.run_label or f"{request.jurisdiction_code}_run"
    normalized = _RUN_FILENAME_SANITIZER.sub("_", run_label).strip("_").lower()
    if not normalized:
        normalized = "run"
    return _RUN_ARTIFACT_ROOT / f"{request.jurisdiction_code.lower()}_{normalized}.json"


def _write_checkpoint(payload: PortalExplorerRunResult) -> None:
    path = Path(payload.checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
