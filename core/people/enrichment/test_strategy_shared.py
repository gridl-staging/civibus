from __future__ import annotations

from hashlib import sha256

import pytest

from core.people.enrichment.strategy_shared import run_strategy_fetch


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

PNG_400X400 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x01\x90\x00\x00\x01\x90\x08\x02\x00\x00\x00"
    b"\x0f\xdd\xa1\x9b"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_run_strategy_fetch_attaches_active_portrait_metadata_when_bytes_pass_quality() -> None:
    record, attempt = run_strategy_fetch(
        source_name="wikidata",
        missing_fields=("portrait_image_url",),
        fetch_payload=lambda: {"portrait_image_url": "https://images.example.org/candidate.png"},
        fetch_portrait_bytes=lambda _url: PNG_400X400,
    )

    assert record.portrait_image_url == "https://images.example.org/candidate.png"
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == "active"
    assert attempt.portrait_metadata is not None
    assert attempt.portrait_metadata.image_hash == sha256(PNG_400X400).hexdigest()
    assert attempt.portrait_metadata.mime_type == "image/png"
    assert attempt.portrait_metadata.width_px == 400
    assert attempt.portrait_metadata.height_px == 400
    assert attempt.portrait_metadata.rights_status == "unknown"


def test_run_strategy_fetch_applies_source_supplied_portrait_rights_without_changing_binary_metadata() -> None:
    record, attempt = run_strategy_fetch(
        source_name="unitedstates/images",
        missing_fields=("portrait_image_url",),
        fetch_payload=lambda: {"portrait_image_url": "https://images.example.org/candidate.jpg"},
        fetch_portrait_bytes=lambda _url: PNG_400X400,
        portrait_rights_status="public_domain",
    )

    assert record.portrait_image_url == "https://images.example.org/candidate.jpg"
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == "active"
    assert attempt.portrait_metadata is not None
    assert attempt.portrait_metadata.image_hash == sha256(PNG_400X400).hexdigest()
    assert attempt.portrait_metadata.mime_type == "image/png"
    assert attempt.portrait_metadata.width_px == 400
    assert attempt.portrait_metadata.height_px == 400
    assert attempt.portrait_metadata.rights_status == "public_domain"


def test_run_strategy_fetch_marks_not_found_only_for_unfetchable_portrait_url() -> None:
    record, attempt = run_strategy_fetch(
        source_name="wikidata",
        missing_fields=("portrait_image_url",),
        fetch_payload=lambda: {"portrait_image_url": "https://images.example.org/missing.png"},
        fetch_portrait_bytes=lambda _url: None,
    )

    assert record.portrait_image_url == "https://images.example.org/missing.png"
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == "not_found"
    assert attempt.portrait_metadata is None


@pytest.mark.parametrize(
    ("image_bytes", "context", "expected_status"),
    [
        (PNG_1X1, {}, "too_small"),
        (
            PNG_400X400,
            {
                "face_box_width_px": 20,
                "face_box_height_px": 20,
            },
            "face_too_small",
        ),
        (b"not-an-image", {}, "rejected"),
    ],
)
def test_run_strategy_fetch_uses_explicit_binary_qa_statuses(
    image_bytes: bytes,
    context: dict[str, int],
    expected_status: str,
) -> None:
    record, attempt = run_strategy_fetch(
        source_name="wikidata",
        missing_fields=("portrait_image_url",),
        fetch_payload=lambda: {
            "portrait_image_url": "https://images.example.org/candidate.png",
            **context,
        },
        fetch_portrait_bytes=lambda _url: image_bytes,
    )

    assert record.portrait_image_url == "https://images.example.org/candidate.png"
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == expected_status
    if expected_status == "rejected":
        assert attempt.portrait_metadata is None
    else:
        assert attempt.portrait_metadata is not None
