from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any

import pytest
from pydantic import ValidationError


def _load_contract_module() -> Any:
    return importlib.import_module("domains.campaign_finance.jurisdictions.portal_explorer.contract")


def test_portal_explorer_modules_define_non_stub_docstrings() -> None:
    module_names = (
        "domains.campaign_finance.jurisdictions.portal_explorer.capture",
        "domains.campaign_finance.jurisdictions.portal_explorer.contract",
        "domains.campaign_finance.jurisdictions.portal_explorer.explorer",
        "domains.campaign_finance.jurisdictions.portal_explorer.proposer",
    )

    for module_name in module_names:
        module = importlib.import_module(module_name)
        doc = module.__doc__
        assert isinstance(doc, str)
        assert doc.strip()
        assert doc.strip() != "Stub summary for explorer.py."


def test_contract_models_reject_unknown_fields() -> None:
    contract = _load_contract_module()

    with pytest.raises(ValidationError):
        contract.PortalExplorerRequest.model_validate(
            {
                "jurisdiction_code": "NC",
                "entry_url": "https://example.gov/portal",
                "unexpected": "nope",
            }
        )


def test_contract_models_round_trip_json() -> None:
    contract = _load_contract_module()

    request = contract.PortalExplorerRequest(
        jurisdiction_code="NC",
        entry_url="https://example.gov/portal",
        run_label="stage-1-seed",
    )
    summary = contract.PortalExplorerRunSummary(
        status="done",
        message="Completed immediately",
        steps_completed=0,
    )
    result = contract.PortalExplorerRunResult(
        request=request,
        summary=summary,
        steps=[],
        checkpoint_path="docs/reference/research/portal_contracts/runs/nc_seed.json",
    )

    for model in (request, summary, result):
        payload = model.model_dump(mode="json")
        restored = type(model).model_validate(payload)
        assert restored == model


def test_package_import_does_not_require_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def _guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("playwright"):
            raise ImportError("blocked playwright import for regression test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    for module_name in (
        "domains.campaign_finance.jurisdictions.portal_explorer",
        "domains.campaign_finance.jurisdictions.portal_explorer.contract",
    ):
        sys.modules.pop(module_name, None)

    package = importlib.import_module("domains.campaign_finance.jurisdictions.portal_explorer")

    assert hasattr(package, "PortalExplorerRequest")
    assert hasattr(package, "PortalExplorerRunResult")


def test_capture_contract_models_round_trip_json() -> None:
    contract = _load_contract_module()

    config = contract.PortalExplorerCaptureConfig(
        dom_text_char_budget=256,
        network_event_budget=5,
        screenshot_byte_budget=4096,
    )
    state = contract.PageState(
        url="https://example.gov/portal",
        title="Example Portal",
        dom_text="Committee filing lookup",
        dom_text_truncated=False,
        screenshot=contract.PageScreenshot(
            base64_png="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
            mime_type="image/png",
        ),
        forms=[
            contract.PageFormDescriptor(
                selector="#search-form",
                method="post",
                action="/search",
                controls=[
                    contract.PageFormControlDescriptor(
                        selector="#CommID",
                        name="CommID",
                        control_type="hidden",
                        value="C123",
                        is_hidden=True,
                    ),
                    contract.PageFormControlDescriptor(
                        selector="#LastName",
                        name="LastName",
                        control_type="text",
                        value="ADAMS",
                        is_hidden=False,
                    ),
                ],
            )
        ],
        recent_requests=[
            contract.PageRequestEvidence(
                method="GET",
                url="https://example.gov/portal?token=__REDACTED__",
                resource_type="document",
                headers={"authorization": "__REDACTED__", "x-trace-id": "abc123"},
            )
        ],
        recent_responses=[
            contract.PageResponseEvidence(
                status=200,
                url="https://example.gov/portal?token=__REDACTED__",
                content_type="text/html",
                content_disposition="",
                content_length="128",
                headers={"set-cookie": "__REDACTED__", "x-trace-id": "abc123"},
            )
        ],
    )

    for model in (config, state):
        payload = model.model_dump(mode="json")
        restored = type(model).model_validate(payload)
        assert restored == model


def test_capture_contract_models_reject_unknown_fields_at_each_nested_level() -> None:
    contract = _load_contract_module()

    with pytest.raises(ValidationError):
        contract.PortalExplorerCaptureConfig.model_validate(
            {
                "dom_text_char_budget": 100,
                "network_event_budget": 10,
                "screenshot_byte_budget": 1024,
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageScreenshot.model_validate(
            {
                "base64_png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
                "mime_type": "image/png",
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageFormControlDescriptor.model_validate(
            {
                "selector": "#LastName",
                "name": "LastName",
                "control_type": "text",
                "value": "ADAMS",
                "is_hidden": False,
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageFormDescriptor.model_validate(
            {
                "selector": "#search-form",
                "method": "post",
                "action": "/search",
                "controls": [],
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageRequestEvidence.model_validate(
            {
                "method": "GET",
                "url": "https://example.gov",
                "resource_type": "document",
                "headers": {},
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageResponseEvidence.model_validate(
            {
                "status": 200,
                "url": "https://example.gov",
                "content_type": "text/html",
                "content_disposition": "",
                "content_length": "100",
                "headers": {},
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        contract.PageState.model_validate(
            {
                "url": "https://example.gov/portal",
                "title": "Portal",
                "dom_text": "Body text",
                "dom_text_truncated": False,
                "screenshot": {
                    "base64_png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
                    "mime_type": "image/png",
                },
                "forms": [],
                "recent_requests": [],
                "recent_responses": [],
                "unexpected": True,
            }
        )


def test_stage4_run_artifacts_support_terminal_statuses() -> None:
    contract = _load_contract_module()
    request = contract.PortalExplorerRequest(
        jurisdiction_code="NC",
        entry_url="https://example.gov/portal",
        run_label="stage-4",
        goal="Find export CSV controls",
        max_steps=2,
    )
    action = contract.PortalExplorerProposedAction(
        action_type="fill",
        selector="#LastName",
        value="ADAMS",
        notes="Input search term",
    )
    step = contract.PortalExplorerStepRecord(
        step_index=0,
        page_url="https://example.gov/portal",
        action=action,
    )

    for terminal_status in ("done", "failed", "exhausted"):
        summary = contract.PortalExplorerRunSummary(
            status=terminal_status,
            message=f"run ended with {terminal_status}",
            steps_completed=1,
            failure_step_index=0 if terminal_status == "failed" else None,
            failure_reason="invalid selector" if terminal_status == "failed" else None,
        )
        result = contract.PortalExplorerRunResult(
            request=request,
            summary=summary,
            steps=[step],
            checkpoint_path="docs/reference/research/portal_contracts/runs/stage_4.json",
        )
        payload = result.model_dump(mode="json")
        restored = contract.PortalExplorerRunResult.model_validate(payload)
        assert restored == result


def test_stage4_run_artifacts_reject_unknown_fields_and_invalid_status() -> None:
    contract = _load_contract_module()

    with pytest.raises(ValidationError):
        contract.PortalExplorerRunSummary.model_validate(
            {
                "status": "placeholder",
                "message": "legacy status should fail",
                "steps_completed": 0,
            }
        )

    with pytest.raises(ValidationError):
        contract.PortalExplorerStepRecord.model_validate(
            {
                "step_index": 0,
                "page_url": "https://example.gov/portal",
                "action": {
                    "action_type": "done",
                    "selector": None,
                    "value": None,
                    "notes": None,
                },
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError):
        contract.PortalExplorerRunResult.model_validate(
            {
                "request": {
                    "jurisdiction_code": "NC",
                    "entry_url": "https://example.gov/portal",
                    "goal": "Find controls",
                    "max_steps": 1,
                },
                "summary": {
                    "status": "done",
                    "message": "complete",
                    "steps_completed": 0,
                },
                "steps": [],
                "checkpoint_path": "docs/reference/research/portal_contracts/runs/sample.json",
                "unexpected": "reject me",
            }
        )
