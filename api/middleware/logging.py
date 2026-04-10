"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar19_02_backend_hardening/civibus_dev/api/middleware/logging.py.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

REQUEST_ID_HEADER_NAME = "X-Request-ID"
_API_LOGGER_NAME = "civibus.api"


def _request_id_from_headers(request: Request) -> str:
    supplied_request_id = request.headers.get(REQUEST_ID_HEADER_NAME)
    if supplied_request_id:
        return supplied_request_id
    return str(uuid.uuid4())


def _request_log_payload(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    exception_type: str | None = None,
) -> str:
    log_payload = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }
    if exception_type is not None:
        log_payload["exception_type"] = exception_type
    return json.dumps(log_payload, sort_keys=True)


def _log_request(
    *,
    logger: logging.Logger,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    exception_type: str | None = None,
) -> None:
    logger.info(
        _request_log_payload(
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            exception_type=exception_type,
        )
    )


def configure_api_json_logger() -> logging.Logger:
    logger = logging.getLogger(_API_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: object) -> None:
        super().__init__(app)
        self._logger = configure_api_json_logger()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        request_id = _request_id_from_headers(request)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            response = PlainTextResponse(
                "Internal Server Error",
                status_code=500,
                headers={REQUEST_ID_HEADER_NAME: request_id},
            )
            _log_request(
                logger=self._logger,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                exception_type=type(exc).__name__,
            )
            return response

        response.headers[REQUEST_ID_HEADER_NAME] = request_id
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _log_request(
            logger=self._logger,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
