from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from pydantic import ValidationError

ValidatedParamsT = TypeVar("ValidatedParamsT", bound=BaseModel)


def _normalize_validation_ctx(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    if ctx is None:
        return None
    normalized_ctx = dict(ctx)
    error = normalized_ctx.get("error")
    if isinstance(error, Exception):
        normalized_ctx["error"] = str(error)
    return normalized_ctx


def request_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    validation_errors: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False):
        error_loc = error.get("loc", ())
        if not isinstance(error_loc, tuple):
            error_loc = tuple(error_loc)
        validation_errors.append(
            {
                **error,
                "ctx": _normalize_validation_ctx(error.get("ctx")),
                "loc": ("query", *error_loc),
            }
        )
    return validation_errors


def build_query_params(request: Request, model_type: type[ValidatedParamsT]) -> ValidatedParamsT:
    try:
        return model_type.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise RequestValidationError(request_validation_errors(exc)) from exc


def build_query_params_dependency(
    model_type: type[ValidatedParamsT],
) -> Callable[[Request], ValidatedParamsT]:
    def dependency(request: Request) -> ValidatedParamsT:
        return build_query_params(request, model_type)

    return dependency
