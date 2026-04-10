from __future__ import annotations


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized_value = str(value).strip()
    if not normalized_value:
        return None
    return normalized_value


__all__ = ["normalize_optional_text"]
