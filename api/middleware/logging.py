"""
Stub summary for mar19_02_backend_hardening/civibus_dev/api/middleware/logging.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

REQUEST_ID_HEADER_NAME = "X-Request-ID"
_API_LOGGER_NAME = "civibus.api"
_HANDLED_EXCEPTION_TYPE_ATTRIBUTE = "civibus_handled_exception_type"
# Caller IDs remain opaque correlations, but must be singleton RFC 9110 tokens.
# This local limit retains UUIDs and known callers while bounding response/log reflection.
_MAX_REQUEST_ID_LENGTH = 128
_REQUEST_ID_TOKEN_PATTERN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


def record_handled_exception_type(request: Request, exception: BaseException) -> None:
    """Attach a safe exception classification to the request's structured log."""
    setattr(request.state, _HANDLED_EXCEPTION_TYPE_ATTRIBUTE, type(exception).__name__)


def _request_id_from_headers(request: Request) -> str:
    supplied_request_ids = request.headers.getlist(REQUEST_ID_HEADER_NAME)
    if len(supplied_request_ids) == 1:
        supplied_request_id = supplied_request_ids[0]
        if (
            0 < len(supplied_request_id) <= _MAX_REQUEST_ID_LENGTH
            and _REQUEST_ID_TOKEN_PATTERN.fullmatch(supplied_request_id) is not None
        ):
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
            exception_type=getattr(request.state, _HANDLED_EXCEPTION_TYPE_ATTRIBUTE, None),
        )
        return response
