from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from domains.campaign_finance.jurisdictions.portal_explorer import (
    PortalExplorerCaptureConfig,
)
from domains.campaign_finance.jurisdictions.portal_explorer.capture import (
    attach_network_capture,
    capture_page_state,
)


@dataclass(frozen=True)
class _MockRequest:
    method: str
    url: str
    resource_type: str
    headers: dict[str, str]


@dataclass(frozen=True)
class _MockResponse:
    status: int
    url: str
    headers: dict[str, str]


class _MockPage:
    def __init__(
        self,
        *,
        url: str,
        title: str,
        screenshot_bytes: bytes,
        dom_text: str,
        forms: list[dict[str, object]],
    ) -> None:
        self.url = url
        self._title = title
        self._screenshot_bytes = screenshot_bytes
        self._snapshot_payload = {
            "dom_text": dom_text,
            "forms": forms,
        }
        self._listeners: dict[str, list[Any]] = {}

    def on(self, event_name: str, callback: Any) -> None:
        self._listeners.setdefault(event_name, []).append(callback)

    def emit(self, event_name: str, payload: object) -> None:
        for callback in self._listeners.get(event_name, []):
            callback(payload)

    def screenshot(self, *, type: str) -> bytes:
        assert type == "png"
        return self._screenshot_bytes

    def title(self) -> str:
        return self._title

    def evaluate(self, _: str) -> dict[str, object]:
        return self._snapshot_payload


def test_capture_page_state_encodes_png_and_enforces_dom_budget() -> None:
    page = _MockPage(
        url="https://example.gov/portal",
        title="Portal",
        screenshot_bytes=b"\x89PNG\r\n\x1a\nbinary",
        dom_text="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        forms=[],
    )
    config = PortalExplorerCaptureConfig(
        dom_text_char_budget=10,
        network_event_budget=5,
        screenshot_byte_budget=1024,
    )

    recorder = attach_network_capture(page, config)
    state = capture_page_state(page, recorder, config)

    assert state.screenshot.base64_png == base64.b64encode(b"\x89PNG\r\n\x1a\nbinary").decode("ascii")
    assert state.screenshot.mime_type == "image/png"
    assert state.dom_text == "ABCDEFGHIJ"
    assert state.dom_text_truncated is True


def test_capture_page_state_normalizes_form_controls() -> None:
    page = _MockPage(
        url="https://example.gov/portal",
        title="Portal",
        screenshot_bytes=b"\x89PNG\r\n\x1a\nbinary",
        dom_text="Search",
        forms=[
            {
                "selector": "#search-form",
                "method": "post",
                "action": "/search",
                "controls": [
                    {
                        "selector": "#CommID",
                        "name": "CommID",
                        "control_type": "hidden",
                        "value": "C123",
                        "is_hidden": True,
                    },
                    {
                        "selector": "#LastName",
                        "name": "LastName",
                        "control_type": "text",
                        "value": "ADAMS",
                        "is_hidden": False,
                    },
                ],
            }
        ],
    )
    config = PortalExplorerCaptureConfig(
        dom_text_char_budget=100,
        network_event_budget=5,
        screenshot_byte_budget=1024,
    )

    recorder = attach_network_capture(page, config)
    state = capture_page_state(page, recorder, config)

    assert len(state.forms) == 1
    assert state.forms[0].selector == "#search-form"
    assert state.forms[0].controls[0].selector == "#CommID"
    assert state.forms[0].controls[0].value == "C123"
    assert state.forms[0].controls[0].is_hidden is True
    assert state.forms[0].controls[1].selector == "#LastName"
    assert state.forms[0].controls[1].value == "ADAMS"


def test_network_capture_is_bounded_and_only_tracks_events_after_attach() -> None:
    page = _MockPage(
        url="https://example.gov/portal",
        title="Portal",
        screenshot_bytes=b"\x89PNG\r\n\x1a\nbinary",
        dom_text="Search",
        forms=[],
    )
    config = PortalExplorerCaptureConfig(
        dom_text_char_budget=100,
        network_event_budget=2,
        screenshot_byte_budget=1024,
    )

    page.emit(
        "request",
        _MockRequest(
            method="GET",
            url="https://example.gov/pre-attach",
            resource_type="document",
            headers={},
        ),
    )
    recorder = attach_network_capture(page, config)
    page.emit(
        "request",
        _MockRequest(method="GET", url="https://example.gov/one", resource_type="document", headers={}),
    )
    page.emit(
        "request",
        _MockRequest(method="GET", url="https://example.gov/two", resource_type="document", headers={}),
    )
    page.emit(
        "request",
        _MockRequest(method="GET", url="https://example.gov/three", resource_type="document", headers={}),
    )
    page.emit(
        "response",
        _MockResponse(status=200, url="https://example.gov/one", headers={"content-type": "text/html"}),
    )
    page.emit(
        "response",
        _MockResponse(status=200, url="https://example.gov/two", headers={"content-type": "text/html"}),
    )
    page.emit(
        "response",
        _MockResponse(status=200, url="https://example.gov/three", headers={"content-type": "text/html"}),
    )

    state = capture_page_state(page, recorder, config)

    assert [request.url for request in state.recent_requests] == [
        "https://example.gov/two",
        "https://example.gov/three",
    ]
    assert [response.url for response in state.recent_responses] == [
        "https://example.gov/two",
        "https://example.gov/three",
    ]


def test_network_capture_redacts_sensitive_query_and_header_values() -> None:
    page = _MockPage(
        url="https://example.gov/portal",
        title="Portal",
        screenshot_bytes=b"\x89PNG\r\n\x1a\nbinary",
        dom_text="Search",
        forms=[],
    )
    config = PortalExplorerCaptureConfig(
        dom_text_char_budget=100,
        network_event_budget=5,
        screenshot_byte_budget=1024,
    )

    recorder = attach_network_capture(page, config)
    page.emit(
        "request",
        _MockRequest(
            method="GET",
            url="https://example.gov/search?q=abc&token=secret&session=abc123",
            resource_type="xhr",
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "session_cookie=abc",
                "X-Trace-Id": "trace-1",
            },
        ),
    )
    page.emit(
        "response",
        _MockResponse(
            status=200,
            url="https://example.gov/search?q=abc&token=secret&sid=abc123",
            headers={
                "content-type": "application/json",
                "set-cookie": "session_cookie=abc",
                "x-api-key": "secret",
                "x-trace-id": "trace-1",
            },
        ),
    )

    state = capture_page_state(page, recorder, config)
    request = state.recent_requests[0]
    response = state.recent_responses[0]

    assert request.url == "https://example.gov/search?q=abc&token=__REDACTED__&session=__REDACTED__"
    assert request.headers["authorization"] == "__REDACTED__"
    assert request.headers["cookie"] == "__REDACTED__"
    assert request.headers["x-trace-id"] == "trace-1"
    assert response.url == "https://example.gov/search?q=abc&token=__REDACTED__&sid=__REDACTED__"
    assert response.headers["set-cookie"] == "__REDACTED__"
    assert response.headers["x-api-key"] == "__REDACTED__"
    assert response.headers["x-trace-id"] == "trace-1"
