from __future__ import annotations

from typing import Any

from domains.campaign_finance.jurisdictions.portal_explorer import contract
from domains.campaign_finance.jurisdictions.portal_explorer import proposer


def _sample_page_state() -> contract.PageState:
    return contract.PageState(
        url="https://example.gov/portal",
        title="Portal",
        dom_text="Search page",
        dom_text_truncated=False,
        screenshot=contract.PageScreenshot(base64_png="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"),
        forms=[
            contract.PageFormDescriptor(
                selector="#search-form",
                method="post",
                action="/search",
                controls=[
                    contract.PageFormControlDescriptor(
                        selector="#LastName",
                        name="LastName",
                        control_type="text",
                        value="",
                        is_hidden=False,
                    )
                ],
            )
        ],
        recent_requests=[],
        recent_responses=[],
    )


def _sample_proposal_input() -> contract.PortalExplorerProposalInput:
    return contract.PortalExplorerProposalInput(
        goal="Submit a last-name search",
        page_state=_sample_page_state(),
        completed_steps=[],
    )


def test_build_proposal_request_payload_is_deterministic() -> None:
    proposal_input = _sample_proposal_input()

    first = proposer.build_proposal_request_payload(proposal_input).model_dump(mode="json")
    second = proposer.build_proposal_request_payload(proposal_input).model_dump(mode="json")

    assert first == second


def test_build_proposal_request_payload_contains_prompt_caching_metadata() -> None:
    payload = proposer.build_proposal_request_payload(_sample_proposal_input()).model_dump(mode="json")

    assert set(payload.keys()) == {"messages", "response_schema"}
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert all(message["cache_control"] == {"type": "ephemeral"} for message in payload["messages"])


def test_propose_next_action_rejects_selector_not_present_in_capture() -> None:
    proposal_input = _sample_proposal_input()

    def _transport(_: contract.PortalExplorerProposalRequestPayload) -> dict[str, Any]:
        return {
            "action_type": "click",
            "selector": "#NotInCapture",
            "value": None,
            "notes": "hallucinated action",
        }

    result = proposer.propose_next_action(proposal_input, transport=_transport)

    assert result.status == "invalid"
    assert result.action is None
    assert result.reason is not None and "selector" in result.reason.lower()


def test_propose_next_action_accepts_valid_selector() -> None:
    proposal_input = _sample_proposal_input()

    def _transport(_: contract.PortalExplorerProposalRequestPayload) -> dict[str, Any]:
        return {
            "action_type": "fill",
            "selector": "#LastName",
            "value": "ADAMS",
            "notes": "fill the search box",
        }

    result = proposer.propose_next_action(proposal_input, transport=_transport)

    assert result.status == "proposed"
    assert result.action is not None
    assert result.action.action_type == "fill"
    assert result.action.selector == "#LastName"
