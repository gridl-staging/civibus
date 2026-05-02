from __future__ import annotations

# Stage 2 seam tests: lock the parser-dispatch registry contract introduced
# alongside the if/elif → PARSER_REGISTRY refactor. Stage 1 characterization
# tests assert end-to-end behavior; these tests assert the registry shape and
# that parse_roster_rows(...) actually dispatches through it.

import pytest

from domains.civics.loaders.official_rosters import parsers
from domains.civics.loaders.official_rosters.parsers import (
    PARSER_REGISTRY,
    _parse_durham_member_rows,
    _parse_nc_house_rows,
    parse_roster_rows,
)


def test_parser_registry_keys_are_exactly_durham_and_nc_house() -> None:
    assert set(PARSER_REGISTRY.keys()) == {"durham_city_council", "nc_house"}


def test_parser_registry_values_resolve_to_existing_parser_functions() -> None:
    assert callable(PARSER_REGISTRY["durham_city_council"])
    assert callable(PARSER_REGISTRY["nc_house"])
    assert PARSER_REGISTRY["durham_city_council"] is _parse_durham_member_rows
    assert PARSER_REGISTRY["nc_house"] is _parse_nc_house_rows


def test_parse_roster_rows_dispatches_through_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_parser(*, source_url: str, html: str) -> list[parsers.NormalizedRosterRow]:
        captured["source_url"] = source_url
        captured["html"] = html
        return []

    patched_registry = dict(PARSER_REGISTRY)
    patched_registry["durham_city_council"] = fake_parser
    monkeypatch.setattr(parsers, "PARSER_REGISTRY", patched_registry)

    result = parse_roster_rows(
        body_key="durham_city_council",
        source_url="https://example.test/roster",
        html="<html></html>",
    )

    assert result == []
    assert captured == {
        "source_url": "https://example.test/roster",
        "html": "<html></html>",
    }
