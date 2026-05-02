from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from domains.campaign_finance.jurisdictions.portal_explorer import contract
from domains.campaign_finance.jurisdictions.portal_explorer import explorer as explorer_module


@dataclass
class _FakePage:
    url: str = "https://example.gov/portal"

    def __post_init__(self) -> None:
        self.goto_calls: list[str] = []
        self.fill_calls: list[tuple[str, str]] = []
        self.click_calls: list[str] = []

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)
        self.url = url

    def fill(self, selector: str, value: str) -> None:
        self.fill_calls.append((selector, value))

    def click(self, selector: str) -> None:
        self.click_calls.append(selector)


@dataclass
class _FakeContext:
    page: _FakePage

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        return None


@dataclass
class _FakeSessionHandle:
    context: _FakeContext
    browser: object | None = None

    def __enter__(self) -> _FakeSessionHandle:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _FakePlaywrightContextManager:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _page_state_with_selectors(*selectors: str) -> contract.PageState:
    return contract.PageState(
        url="https://example.gov/portal",
        title="Portal",
        dom_text="Portal body",
        dom_text_truncated=False,
        screenshot=contract.PageScreenshot(base64_png="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"),
        forms=[
            contract.PageFormDescriptor(
                selector="#search-form",
                method="post",
                action="/search",
                controls=[
                    contract.PageFormControlDescriptor(
                        selector=selector,
                        name=selector.lstrip("#"),
                        control_type="text",
                        value="",
                        is_hidden=False,
                    )
                    for selector in selectors
                ],
            )
        ],
        recent_requests=[],
        recent_responses=[],
    )


def _request(*, max_steps: int = 3, run_label: str = "stage-4") -> contract.PortalExplorerRequest:
    return contract.PortalExplorerRequest(
        jurisdiction_code="NC",
        entry_url="https://example.gov/portal",
        run_label=run_label,
        goal="Find export controls",
        max_steps=max_steps,
    )


def _configure_browser_and_capture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    page: _FakePage,
    states: list[contract.PageState],
) -> None:
    monkeypatch.setattr(explorer_module, "open_playwright", lambda _: _FakePlaywrightContextManager())
    monkeypatch.setattr(
        explorer_module,
        "launch_browser_session",
        lambda _playwright, _settings: _FakeSessionHandle(context=_FakeContext(page=page)),
    )
    monkeypatch.setattr(explorer_module, "attach_network_capture", lambda _page, _config: object())
    state_iter = iter(states)
    monkeypatch.setattr(explorer_module, "capture_page_state", lambda _page, _recorder, _config: next(state_iter))


def test_run_signature_is_stable() -> None:
    signature = inspect.signature(explorer_module.run)

    assert list(signature.parameters) == ["request"]
    assert signature.parameters["request"].annotation is contract.PortalExplorerRequest


def test_run_returns_done_when_proposer_emits_done(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    _configure_browser_and_capture(monkeypatch, page=page, states=[_page_state_with_selectors("#LastName")])
    monkeypatch.setattr(
        explorer_module,
        "propose_next_action",
        lambda _input, transport=None: contract.PortalExplorerProposalResult(
            status="proposed",
            action=contract.PortalExplorerProposedAction(action_type="done", notes="all done"),
        ),
    )

    checkpoints: list[contract.PortalExplorerRunResult] = []
    monkeypatch.setattr(explorer_module, "_write_checkpoint", lambda payload: checkpoints.append(payload))

    result = explorer_module.run(_request())

    assert result.summary.status == "done"
    assert result.summary.steps_completed == 1
    assert result.steps[-1].action.action_type == "done"
    assert page.goto_calls == ["https://example.gov/portal"]
    assert checkpoints[-1].summary.status == "done"


def test_run_fails_when_proposer_returns_selector_outside_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    _configure_browser_and_capture(monkeypatch, page=page, states=[_page_state_with_selectors("#LastName")])
    monkeypatch.setattr(
        explorer_module,
        "propose_next_action",
        lambda _input, transport=None: contract.PortalExplorerProposalResult(
            status="proposed",
            action=contract.PortalExplorerProposedAction(
                action_type="click",
                selector="#NotInCapture",
                notes="hallucinated selector",
            ),
        ),
    )
    monkeypatch.setattr(explorer_module, "_write_checkpoint", lambda payload: None)

    result = explorer_module.run(_request())

    assert result.summary.status == "failed"
    assert result.summary.failure_step_index == 0
    assert "selector" in (result.summary.failure_reason or "").lower()
    assert page.click_calls == []


def test_run_returns_exhausted_when_max_steps_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    _configure_browser_and_capture(
        monkeypatch,
        page=page,
        states=[_page_state_with_selectors("#LastName"), _page_state_with_selectors("#LastName")],
    )
    monkeypatch.setattr(
        explorer_module,
        "propose_next_action",
        lambda _input, transport=None: contract.PortalExplorerProposalResult(
            status="proposed",
            action=contract.PortalExplorerProposedAction(action_type="click", selector="#LastName"),
        ),
    )

    checkpoints: list[contract.PortalExplorerRunResult] = []
    monkeypatch.setattr(explorer_module, "_write_checkpoint", lambda payload: checkpoints.append(payload))

    result = explorer_module.run(_request(max_steps=2))

    assert result.summary.status == "exhausted"
    assert result.summary.steps_completed == 2
    assert len(page.click_calls) == 2
    assert checkpoints[-1].summary.status == "exhausted"


def test_run_result_serialization_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    def _execute_once() -> dict[str, Any]:
        page = _FakePage()
        _configure_browser_and_capture(monkeypatch, page=page, states=[_page_state_with_selectors("#LastName")])
        monkeypatch.setattr(
            explorer_module,
            "propose_next_action",
            lambda _input, transport=None: contract.PortalExplorerProposalResult(
                status="proposed",
                action=contract.PortalExplorerProposedAction(action_type="done"),
            ),
        )
        monkeypatch.setattr(explorer_module, "_write_checkpoint", lambda payload: None)
        return explorer_module.run(_request(run_label="deterministic")).model_dump(mode="json")

    first = _execute_once()
    second = _execute_once()

    assert first == second


def test_checkpoint_persists_after_each_completed_step_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = _FakePage()
    _configure_browser_and_capture(
        monkeypatch,
        page=page,
        states=[
            _page_state_with_selectors("#LastName"),
            _page_state_with_selectors("#LastName"),
        ],
    )
    decisions = iter(
        [
            contract.PortalExplorerProposalResult(
                status="proposed",
                action=contract.PortalExplorerProposedAction(action_type="fill", selector="#LastName", value="ADAMS"),
            ),
            contract.PortalExplorerProposalResult(
                status="proposed",
                action=contract.PortalExplorerProposedAction(action_type="done"),
            ),
        ]
    )
    monkeypatch.setattr(explorer_module, "propose_next_action", lambda _input, transport=None: next(decisions))
    monkeypatch.setattr(explorer_module, "_RUN_ARTIFACT_ROOT", tmp_path)

    checkpoints: list[contract.PortalExplorerRunResult] = []
    monkeypatch.setattr(explorer_module, "_write_checkpoint", lambda payload: checkpoints.append(payload))

    result = explorer_module.run(_request(max_steps=3, run_label="checkpoint"))

    assert result.summary.status == "done"
    assert len(checkpoints) == 2
    assert checkpoints[0].summary.steps_completed == 1
    assert checkpoints[-1].summary.status == "done"
