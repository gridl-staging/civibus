from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_ROSTER_CADENCE = "weekly"


@dataclass(frozen=True, slots=True)
class RosterSourceMetadata:
    """Canonical roster metadata parsed from sources.yaml."""

    source_id: str
    name: str
    source_url: str
    body_key: str
    cadence: str
    jurisdiction: str

    @property
    def notes_payload(self) -> dict[str, object]:
        return {
            "roster_source": True,
            "registry_source_id": self.source_id,
            "body_key": self.body_key,
        }

    @property
    def notes_json(self) -> str:
        return json.dumps(self.notes_payload, sort_keys=True)


def _coerce_nonempty_string(value: object, *, field_name: str, source_id: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"source {source_id} {field_name} must be non-empty")
    return value.strip()


def _extract_roster_cadence(source_id: str, source: dict[str, object], roster_bootstrap: dict[str, object]) -> str:
    raw_cadence = (
        roster_bootstrap.get("cadence")
        or roster_bootstrap.get("update_frequency")
        or source.get("cadence")
        or source.get("update_frequency")
        or _DEFAULT_ROSTER_CADENCE
    )
    return _coerce_nonempty_string(raw_cadence, field_name="cadence", source_id=source_id)


@lru_cache(maxsize=1)
def _load_sources_registry() -> dict[str, object]:
    payload = yaml.safe_load((_REPO_ROOT / "sources.yaml").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sources.yaml must contain a mapping at top level")
    return payload


def list_nc_roster_source_metadata() -> tuple[RosterSourceMetadata, ...]:
    """Return NC roster-source metadata from the canonical registry owner."""

    payload = _load_sources_registry()
    jurisdictions = payload.get("jurisdictions")
    if not isinstance(jurisdictions, list):
        raise ValueError("sources.yaml jurisdictions must be a list")

    for jurisdiction in jurisdictions:
        if not isinstance(jurisdiction, dict):
            continue
        if jurisdiction.get("scope") != "NC":
            continue

        sources = jurisdiction.get("sources")
        if not isinstance(sources, list):
            raise ValueError("NC sources registry block must contain a list")

        resolved_sources: list[RosterSourceMetadata] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            roster_bootstrap = source.get("roster_bootstrap")
            if roster_bootstrap is None:
                continue
            if not isinstance(roster_bootstrap, dict):
                raise ValueError("roster_bootstrap must be a mapping when provided")

            source_id = _coerce_nonempty_string(
                source.get("source_id"),
                field_name="source_id",
                source_id="<unknown>",
            )
            resolved_sources.append(
                RosterSourceMetadata(
                    source_id=source_id,
                    name=_coerce_nonempty_string(
                        roster_bootstrap.get("name"),
                        field_name="roster_bootstrap.name",
                        source_id=source_id,
                    ),
                    source_url=_coerce_nonempty_string(
                        roster_bootstrap.get("source_url"),
                        field_name="roster_bootstrap.source_url",
                        source_id=source_id,
                    ),
                    body_key=_coerce_nonempty_string(
                        roster_bootstrap.get("body_key"),
                        field_name="roster_bootstrap.body_key",
                        source_id=source_id,
                    ),
                    cadence=_extract_roster_cadence(source_id, source, roster_bootstrap),
                    jurisdiction="state/NC",
                )
            )
        return tuple(resolved_sources)

    raise ValueError("sources.yaml missing NC jurisdiction block")
