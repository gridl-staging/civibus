"""Capture sanitized page-state and network evidence for portal explorer steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import base64
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from domains.campaign_finance.jurisdictions.portal_explorer.contract import (
    PageFormControlDescriptor,
    PageFormDescriptor,
    PageRequestEvidence,
    PageResponseEvidence,
    PageScreenshot,
    PageState,
    PortalExplorerCaptureConfig,
)

_REDACTED = "__REDACTED__"

# Reuses the NC probe-style sensitive key contract and extends it with
# x-api-key to keep common API-key header naming redacted by default.
_SENSITIVE_NETWORK_KEYS = frozenset(
    {
        "token",
        "session",
        "sessionid",
        "sid",
        "set-cookie",
        "cookie",
        "auth",
        "authorization",
        "apikey",
        "api_key",
        "key",
        "x-api-key",
    }
)

_DOM_CAPTURE_SCRIPT = """
() => {
    const bodyText = (document.body?.innerText || "").replace(/\\s+/g, " ").trim();
    const forms = Array.from(document.forms || []).map((form, formIndex) => {
        const formSelector = form.id ? `#${form.id}` : `form:nth-of-type(${formIndex + 1})`;
        const controls = Array.from(form.elements || []).map((control, controlIndex) => {
            const name = control.getAttribute("name") || "";
            const controlType = (
                control.getAttribute("type")
                || control.tagName
                || ""
            ).toLowerCase();
            const selector = control.id
                ? `#${control.id}`
                : name
                    ? `[name="${name}"]`
                    : `${control.tagName.toLowerCase()}:nth-of-type(${controlIndex + 1})`;
            return {
                selector,
                name,
                control_type: controlType,
                value: (control.value || "").toString(),
                is_hidden: controlType === "hidden",
            };
        });
        return {
            selector: formSelector,
            method: (form.getAttribute("method") || "get").toLowerCase(),
            action: form.getAttribute("action") || "",
            controls,
        };
    });
    return { dom_text: bodyText, forms };
}
"""


def _sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    sanitized_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_NETWORK_KEYS:
            sanitized_pairs.append((key, _REDACTED))
            continue
        sanitized_pairs.append((key, value))

    sanitized_query = urlencode(sanitized_pairs, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            sanitized_query,
            parsed.fragment,
        )
    )


def _sanitize_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}

    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        normalized_key = str(key).lower()
        sanitized[normalized_key] = _REDACTED if normalized_key in _SENSITIVE_NETWORK_KEYS else str(value)
    return sanitized


def _trim_dom_text(dom_text: str, char_budget: int) -> tuple[str, bool]:
    if len(dom_text) <= char_budget:
        return dom_text, False
    return dom_text[:char_budget], True


def _append_bounded[T](items: list[T], item: T, budget: int) -> None:
    items.append(item)
    overflow = len(items) - budget
    if overflow > 0:
        del items[0:overflow]


def _to_form_control_descriptor(raw_control: Mapping[str, object]) -> PageFormControlDescriptor:
    selector = str(raw_control.get("selector", ""))
    name = str(raw_control.get("name", ""))
    control_type = str(raw_control.get("control_type") or raw_control.get("type") or "")
    value = str(raw_control.get("value", ""))
    is_hidden = bool(raw_control.get("is_hidden", control_type == "hidden"))
    return PageFormControlDescriptor(
        selector=selector,
        name=name,
        control_type=control_type,
        value=value,
        is_hidden=is_hidden,
    )


def _to_form_descriptor(raw_form: Mapping[str, object]) -> PageFormDescriptor:
    raw_controls = raw_form.get("controls")
    controls: list[PageFormControlDescriptor] = []
    if isinstance(raw_controls, list):
        for raw_control in raw_controls:
            if isinstance(raw_control, Mapping):
                controls.append(_to_form_control_descriptor(raw_control))

    return PageFormDescriptor(
        selector=str(raw_form.get("selector", "")),
        method=str(raw_form.get("method", "")),
        action=str(raw_form.get("action", "")),
        controls=controls,
    )


def _snapshot_dom_and_forms(page: object) -> tuple[str, list[PageFormDescriptor]]:
    payload = page.evaluate(_DOM_CAPTURE_SCRIPT)  # type: ignore[union-attr]
    if not isinstance(payload, Mapping):
        return "", []

    dom_text = str(payload.get("dom_text", ""))
    forms: list[PageFormDescriptor] = []
    raw_forms = payload.get("forms")
    if isinstance(raw_forms, list):
        for raw_form in raw_forms:
            if isinstance(raw_form, Mapping):
                forms.append(_to_form_descriptor(raw_form))
    return dom_text, forms


@dataclass(slots=True)
class NetworkCaptureRecorder:
    """Bounded request/response event recorder attached to an existing page."""

    network_event_budget: int
    _requests: list[PageRequestEvidence] = field(default_factory=list)
    _responses: list[PageResponseEvidence] = field(default_factory=list)

    def record_request(self, request: object) -> None:
        request_headers = _sanitize_headers(getattr(request, "headers", None))
        request_evidence = PageRequestEvidence(
            method=str(getattr(request, "method", "")),
            url=_sanitize_url(str(getattr(request, "url", ""))),
            resource_type=str(getattr(request, "resource_type", "")),
            headers=request_headers,
        )
        _append_bounded(self._requests, request_evidence, self.network_event_budget)

    def record_response(self, response: object) -> None:
        response_headers = _sanitize_headers(getattr(response, "headers", None))
        response_evidence = PageResponseEvidence(
            status=int(getattr(response, "status", 0)),
            url=_sanitize_url(str(getattr(response, "url", ""))),
            content_type=response_headers.get("content-type", ""),
            content_disposition=response_headers.get("content-disposition", ""),
            content_length=response_headers.get("content-length", ""),
            headers=response_headers,
        )
        _append_bounded(self._responses, response_evidence, self.network_event_budget)

    def recent_requests(self) -> list[PageRequestEvidence]:
        return list(self._requests)

    def recent_responses(self) -> list[PageResponseEvidence]:
        return list(self._responses)


def attach_network_capture(
    page: object,
    config: PortalExplorerCaptureConfig,
) -> NetworkCaptureRecorder:
    recorder = NetworkCaptureRecorder(network_event_budget=config.network_event_budget)
    page.on("request", recorder.record_request)  # type: ignore[union-attr]
    page.on("response", recorder.record_response)  # type: ignore[union-attr]
    return recorder


def capture_page_state(
    page: object,
    recorder: NetworkCaptureRecorder,
    config: PortalExplorerCaptureConfig,
) -> PageState:
    screenshot_bytes = page.screenshot(type="png")  # type: ignore[union-attr]
    if len(screenshot_bytes) > config.screenshot_byte_budget:
        raise ValueError(
            "PNG screenshot exceeds configured screenshot_byte_budget "
            f"({len(screenshot_bytes)} > {config.screenshot_byte_budget})"
        )

    base64_png = base64.b64encode(screenshot_bytes).decode("ascii")
    dom_text, forms = _snapshot_dom_and_forms(page)
    trimmed_dom_text, dom_text_truncated = _trim_dom_text(dom_text, config.dom_text_char_budget)
    title = page.title()  # type: ignore[union-attr]

    return PageState(
        url=str(getattr(page, "url", "")),
        title=str(title),
        dom_text=trimmed_dom_text,
        dom_text_truncated=dom_text_truncated,
        screenshot=PageScreenshot(base64_png=base64_png),
        forms=forms,
        recent_requests=recorder.recent_requests(),
        recent_responses=recorder.recent_responses(),
    )
