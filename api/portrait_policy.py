"""Shared API portrait exposure rules."""

from __future__ import annotations

REUSABLE_PORTRAIT_RIGHTS_STATUSES = frozenset({"licensed", "public_domain"})


def reusable_portrait_rights_statuses() -> tuple[str, ...]:
    return tuple(sorted(REUSABLE_PORTRAIT_RIGHTS_STATUSES))


def suppress_non_reusable_portrait_url(source_image_url: str | None, rights_status: str | None) -> str | None:
    if rights_status not in REUSABLE_PORTRAIT_RIGHTS_STATUSES:
        return None
    return source_image_url
