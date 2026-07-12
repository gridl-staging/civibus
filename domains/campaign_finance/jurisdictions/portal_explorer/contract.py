"""Define strict typed contracts for portal explorer requests, state, and proposals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortalExplorerBaseModel(BaseModel):
    """Shared strict base model for portal explorer contracts."""

    model_config = ConfigDict(extra="forbid")


class PortalExplorerCaptureConfig(PortalExplorerBaseModel):
    """Capture budgets for deterministic browser-to-contract snapshots."""

    dom_text_char_budget: int = Field(default=12_000, ge=1)
    network_event_budget: int = Field(default=100, ge=1)
    screenshot_byte_budget: int = Field(default=2_000_000, ge=1)


class PortalExplorerRequest(PortalExplorerBaseModel):
    """Top-level typed input for a portal explorer run."""

    jurisdiction_code: str
    entry_url: str
    run_label: str | None = None
    goal: str = "Identify the next safe portal interaction."
    max_steps: int = Field(default=3, ge=1)
    capture_config: PortalExplorerCaptureConfig = Field(default_factory=PortalExplorerCaptureConfig)


class PageScreenshot(PortalExplorerBaseModel):
    """JSON-safe screenshot payload for prompt-ready page snapshots."""

    base64_png: str
    mime_type: Literal["image/png"] = "image/png"


class PageFormControlDescriptor(PortalExplorerBaseModel):
    """Normalized form-control descriptor aligned with NC selector/value evidence style."""

    selector: str
    name: str
    control_type: str
    value: str
    is_hidden: bool


class PageFormDescriptor(PortalExplorerBaseModel):
    """Normalized form descriptor for selector-based action validation."""

    selector: str
    method: str
    action: str
    controls: list[PageFormControlDescriptor]


class PageRequestEvidence(PortalExplorerBaseModel):
    """Request evidence row recorded from page-level Playwright events."""

    method: str
    url: str
    resource_type: str
    headers: dict[str, str] = Field(default_factory=dict)


class PageResponseEvidence(PortalExplorerBaseModel):
    """Response evidence row recorded from page-level Playwright events."""

    status: int
    url: str
    content_type: str
    content_disposition: str
    content_length: str
    headers: dict[str, str] = Field(default_factory=dict)


class PageState(PortalExplorerBaseModel):
    """Compact browser snapshot contract consumed by later explorer stages."""

    url: str
    title: str
    dom_text: str
    dom_text_truncated: bool
    screenshot: PageScreenshot
    forms: list[PageFormDescriptor]
    recent_requests: list[PageRequestEvidence]
    recent_responses: list[PageResponseEvidence]


class PortalExplorerProposedAction(PortalExplorerBaseModel):
    """Typed proposer action with strict action-shape validation."""

    action_type: Literal["click", "fill", "done"]
    selector: str | None = None
    value: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_action_shape(self) -> PortalExplorerProposedAction:
        if self.action_type == "done":
            if self.selector is not None or self.value is not None:
                raise ValueError("done action must not include selector or value")
            return self
        if self.selector is None or not self.selector.strip():
            raise ValueError(f"{self.action_type} action requires a non-empty selector")
        if self.action_type == "click" and self.value is not None:
            raise ValueError("click action must not include value")
        if self.action_type == "fill" and self.value is None:
            raise ValueError("fill action requires value")
        return self


class PortalExplorerStepRecord(PortalExplorerBaseModel):
    """Per-step audit record captured by the run loop."""

    step_index: int = Field(ge=0)
    page_url: str
    action: PortalExplorerProposedAction


class PortalExplorerProposalInput(PortalExplorerBaseModel):
    """Structured proposer input for transport-agnostic decision making."""

    goal: str
    page_state: PageState
    completed_steps: list[PortalExplorerStepRecord] = Field(default_factory=list)


class PortalExplorerPromptCacheControl(PortalExplorerBaseModel):
    """Prompt cache-control metadata for model-facing payloads."""

    type: Literal["ephemeral"] = "ephemeral"


class PortalExplorerPromptMessage(PortalExplorerBaseModel):
    """Message row used in model-facing proposer request payloads."""

    role: Literal["system", "user"]
    content: str
    cache_control: PortalExplorerPromptCacheControl = Field(default_factory=PortalExplorerPromptCacheControl)


class PortalExplorerProposalRequestPayload(PortalExplorerBaseModel):
    """Typed transport payload generated from proposal input."""

    messages: list[PortalExplorerPromptMessage]
    response_schema: dict[str, Any]


class PortalExplorerProposalResult(PortalExplorerBaseModel):
    """Typed proposer outcome consumed by the explorer loop."""

    status: Literal["proposed", "invalid"]
    action: PortalExplorerProposedAction | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_result_shape(self) -> PortalExplorerProposalResult:
        if self.status == "proposed" and self.action is None:
            raise ValueError("proposed status requires action")
        if self.status == "invalid":
            if self.action is not None:
                raise ValueError("invalid status must not include action")
            if self.reason is None or not self.reason.strip():
                raise ValueError("invalid status requires reason")
        return self


class PortalExplorerRunSummary(PortalExplorerBaseModel):
    """Summary status returned by the bounded run loop."""

    status: Literal["running", "done", "failed", "exhausted"]
    message: str
    steps_completed: int = Field(ge=0)
    failure_step_index: int | None = Field(default=None, ge=0)
    failure_reason: str | None = None

    @model_validator(mode="after")
    def _validate_failure_fields(self) -> PortalExplorerRunSummary:
        if self.status == "failed":
            if self.failure_step_index is None:
                raise ValueError("failed status requires failure_step_index")
            if self.failure_reason is None or not self.failure_reason.strip():
                raise ValueError("failed status requires failure_reason")
            return self
        if self.failure_step_index is not None or self.failure_reason is not None:
            raise ValueError("failure_step_index and failure_reason are only valid when status='failed'")
        return self


class PortalExplorerRunResult(PortalExplorerBaseModel):
    """Top-level typed output and checkpoint payload for an explorer run."""

    request: PortalExplorerRequest
    summary: PortalExplorerRunSummary
    steps: list[PortalExplorerStepRecord] = Field(default_factory=list)
    checkpoint_path: str


__all__ = [
    "PageFormControlDescriptor",
    "PageFormDescriptor",
    "PageRequestEvidence",
    "PageResponseEvidence",
    "PageScreenshot",
    "PageState",
    "PortalExplorerBaseModel",
    "PortalExplorerCaptureConfig",
    "PortalExplorerPromptCacheControl",
    "PortalExplorerPromptMessage",
    "PortalExplorerProposalInput",
    "PortalExplorerProposalRequestPayload",
    "PortalExplorerProposalResult",
    "PortalExplorerProposedAction",
    "PortalExplorerRequest",
    "PortalExplorerRunResult",
    "PortalExplorerRunSummary",
    "PortalExplorerStepRecord",
]
