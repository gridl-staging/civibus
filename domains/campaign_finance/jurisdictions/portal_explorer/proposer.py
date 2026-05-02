"""Build and validate portal explorer proposal actions via a pluggable transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from pydantic import ValidationError

from domains.campaign_finance.jurisdictions.portal_explorer.contract import (
    PageState,
    PortalExplorerProposalInput,
    PortalExplorerProposalRequestPayload,
    PortalExplorerProposalResult,
    PortalExplorerProposedAction,
    PortalExplorerPromptMessage,
)


type ProposalTransport = Callable[[PortalExplorerProposalRequestPayload], Mapping[str, Any]]


def build_proposal_request_payload(
    proposal_input: PortalExplorerProposalInput,
) -> PortalExplorerProposalRequestPayload:
    """Build a deterministic transport payload for next-action proposal."""
    user_payload = {
        "goal": proposal_input.goal,
        "page_state": proposal_input.page_state.model_dump(mode="json"),
        "completed_steps": [step.model_dump(mode="json") for step in proposal_input.completed_steps],
    }
    system_message = PortalExplorerPromptMessage(
        role="system",
        content=(
            "Return one portal action as JSON. Allowed action_type values are "
            "'click', 'fill', and 'done'."
        ),
    )
    user_message = PortalExplorerPromptMessage(
        role="user",
        content=json.dumps(user_payload, sort_keys=True, separators=(",", ":")),
    )
    return PortalExplorerProposalRequestPayload(
        messages=[system_message, user_message],
        response_schema=PortalExplorerProposedAction.model_json_schema(mode="validation"),
    )


def validate_action_against_page_state(
    action: PortalExplorerProposedAction,
    page_state: PageState,
) -> PortalExplorerProposalResult:
    """Validate selector-scoped actions against selectors captured from the page."""
    if action.action_type == "done":
        return PortalExplorerProposalResult(status="proposed", action=action)
    selector_universe = _selector_universe(page_state)
    if action.selector not in selector_universe:
        return PortalExplorerProposalResult(
            status="invalid",
            reason=(
                f"Action selector {action.selector!r} is not present in captured selector universe"
            ),
        )
    return PortalExplorerProposalResult(status="proposed", action=action)


def propose_next_action(
    proposal_input: PortalExplorerProposalInput,
    *,
    transport: ProposalTransport | None = None,
) -> PortalExplorerProposalResult:
    """Ask the proposal transport for the next action and validate it."""
    if transport is None:
        return PortalExplorerProposalResult(
            status="invalid",
            reason="No proposal transport configured for proposer",
        )

    payload = build_proposal_request_payload(proposal_input)
    try:
        response_payload = transport(payload)
    except Exception as error:  # noqa: BLE001
        return PortalExplorerProposalResult(
            status="invalid",
            reason=f"Proposal transport failed: {error}",
        )

    try:
        action = PortalExplorerProposedAction.model_validate(response_payload)
    except ValidationError as error:
        return PortalExplorerProposalResult(
            status="invalid",
            reason=f"Proposal payload failed validation: {error}",
        )

    return validate_action_against_page_state(action, proposal_input.page_state)


def _selector_universe(page_state: PageState) -> set[str]:
    selectors: set[str] = set()
    for form in page_state.forms:
        if form.selector:
            selectors.add(form.selector)
        for control in form.controls:
            if control.selector:
                selectors.add(control.selector)
    return selectors


__all__ = [
    "ProposalTransport",
    "build_proposal_request_payload",
    "propose_next_action",
    "validate_action_against_page_state",
]
