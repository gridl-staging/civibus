"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/__init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(frozen=True, slots=True)
class _NCDataSourceBlock:
    name: str
    lines: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_nc_data_source_blocks() -> tuple[_NCDataSourceBlock, ...]:
    blocks: list[_NCDataSourceBlock] = []
    current_name: str | None = None
    current_lines: list[str] = []
    in_data_sources_block = False

    for line in _CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("data_sources:"):
            in_data_sources_block = True
            continue
        if not in_data_sources_block:
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("  - name:"):
            if current_name is not None:
                blocks.append(_NCDataSourceBlock(name=current_name, lines=tuple(current_lines)))
            current_name = line.strip().removeprefix("- name:").strip().strip('"')
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        blocks.append(_NCDataSourceBlock(name=current_name, lines=tuple(current_lines)))

    return tuple(blocks)


def _find_nc_data_source_block(source_name: str) -> _NCDataSourceBlock | None:
    for block in _load_nc_data_source_blocks():
        if block.name == source_name:
            return block
    return None
