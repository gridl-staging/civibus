
from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from struct import unpack

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    EnrichmentAttempt,
    JsonLikeMapping,
    PortraitBinaryMetadata,
    PortraitQaStatus,
)

MIN_PORTRAIT_DIMENSION_PX = 128
MIN_FACE_AREA_RATIO = 0.015
DEFAULT_HTTP_HEADERS = {
    # A stable desktop UA avoids some overly aggressive bot heuristics on public sites.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


class UnwiredDefaultFetcherError(RuntimeError):
    """Raised when a strategy default fetcher is still using placeholder wiring."""

    def __init__(self, source_name: str) -> None:
        super().__init__(f"unwired default fetcher: {source_name}")


def fetch_bytes_via_http(url: str, *, timeout_seconds: float) -> bytes | None:
    """Fetch portrait bytes over HTTP and treat common not-found responses as empty."""
    response = httpx.get(url, headers=DEFAULT_HTTP_HEADERS, timeout=timeout_seconds, follow_redirects=True)
    if response.status_code in {202, 403, 404, 410, 429}:
        return None
    response.raise_for_status()
    return response.content


def record_from_payload(payload: JsonLikeMapping | None, missing_fields: tuple[str, ...]) -> CandidateEnrichmentRecord:
    """Build a partial enrichment record from payload keys matching missing fields."""
    if not payload:
        return CandidateEnrichmentRecord()

    record_kwargs: dict[str, str] = {}
    for field_name in missing_fields:
        field_value = payload.get(field_name)
        if isinstance(field_value, str) and field_value.strip() != "":
            record_kwargs[field_name] = field_value.strip()

    return CandidateEnrichmentRecord(**record_kwargs)


def _parse_image_dimensions(image_bytes: bytes) -> tuple[str, int, int] | None:
    if len(image_bytes) < 10:
        return None

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        width_px, height_px = unpack(">II", image_bytes[16:24])
        return "image/png", width_px, height_px

    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        width_px, height_px = unpack("<HH", image_bytes[6:10])
        return "image/gif", width_px, height_px

    if image_bytes.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(image_bytes):
            if image_bytes[offset] != 0xFF:
                offset += 1
                continue
            marker = image_bytes[offset + 1]
            if marker in {0xD8, 0xD9}:
                offset += 2
                continue
            segment_length = int.from_bytes(image_bytes[offset + 2 : offset + 4], "big")
            if segment_length < 2 or offset + 2 + segment_length > len(image_bytes):
                return None
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC9, 0xCA, 0xCB}:
                height_px = int.from_bytes(image_bytes[offset + 5 : offset + 7], "big")
                width_px = int.from_bytes(image_bytes[offset + 7 : offset + 9], "big")
                return "image/jpeg", width_px, height_px
            offset += 2 + segment_length
    return None


def _extract_face_box_dimensions(payload: JsonLikeMapping | None) -> tuple[int, int] | None:
    if payload is None:
        return None
    width_value = payload.get("face_box_width_px")
    height_value = payload.get("face_box_height_px")
    if isinstance(width_value, int) and isinstance(height_value, int) and width_value > 0 and height_value > 0:
        return width_value, height_value
    return None


def evaluate_portrait_binary(
    image_bytes: bytes,
    *,
    source_image_url: str,
    face_box_dimensions_px: tuple[int, int] | None = None,
) -> tuple[PortraitQaStatus, PortraitBinaryMetadata | None]:
    parsed = _parse_image_dimensions(image_bytes)
    if parsed is None:
        return "rejected", None

    mime_type, width_px, height_px = parsed
    metadata = PortraitBinaryMetadata(
        image_hash=sha256(image_bytes).hexdigest(),
        mime_type=mime_type,
        width_px=width_px,
        height_px=height_px,
        source_image_url=source_image_url,
    )

    # Width/height gating keeps obviously unusable assets out of active portrait slots.
    if min(width_px, height_px) < MIN_PORTRAIT_DIMENSION_PX:
        return "too_small", metadata

    # If a source provides explicit face-box dimensions, enforce a minimum face-area ratio.
    if face_box_dimensions_px is not None:
        face_width, face_height = face_box_dimensions_px
        face_area_ratio = (face_width * face_height) / (width_px * height_px)
        if face_area_ratio < MIN_FACE_AREA_RATIO:
            return "face_too_small", metadata

    return "active", metadata


def run_strategy_fetch(
    *,
    source_name: str,
    missing_fields: tuple[str, ...],
    fetch_payload: Callable[[], JsonLikeMapping | None],
    fetch_portrait_bytes: Callable[[str], bytes | None] | None = None,
) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
    """Normalize one strategy fetch into a record plus structured attempt metadata."""
    try:
        payload = fetch_payload()
    except Exception as error:  # noqa: BLE001 - strategy records failure metadata instead of raising.
        return CandidateEnrichmentRecord(), EnrichmentAttempt.failed(
            source=source_name,
            requested_fields=missing_fields,
            error_message=str(error),
        )

    record = record_from_payload(payload, missing_fields)
    if record == CandidateEnrichmentRecord():
        return record, EnrichmentAttempt.no_data(source=source_name, requested_fields=missing_fields)

    contributed_fields = tuple(field for field in missing_fields if getattr(record, field) not in (None, ""))
    attempt = EnrichmentAttempt.success(
        source=source_name,
        requested_fields=missing_fields,
        contributed_fields=contributed_fields,
    )
    portrait_url = record.portrait_image_url
    if portrait_url in (None, "") or fetch_portrait_bytes is None:
        return record, attempt

    try:
        image_bytes = fetch_portrait_bytes(portrait_url)
    except Exception:  # noqa: BLE001 - failed portrait fetch is an explicit non-active outcome.
        image_bytes = None

    if image_bytes is None or image_bytes == b"":
        return record, attempt.model_copy(
            update={"portrait_status": "not_found", "metadata": {**attempt.metadata, "portrait_fetch_outcome": "not_found"}}
        )

    portrait_status, portrait_metadata = evaluate_portrait_binary(
        image_bytes,
        source_image_url=portrait_url,
        face_box_dimensions_px=_extract_face_box_dimensions(payload),
    )
    record.portrait_metadata = portrait_metadata
    if portrait_status == "rejected":
        return record, attempt.model_copy(
            update={"portrait_status": portrait_status, "metadata": {**attempt.metadata, "portrait_rejection_reason": "invalid_image_bytes"}}
        )
    return record, attempt.model_copy(update={"portrait_status": portrait_status, "portrait_metadata": portrait_metadata})
