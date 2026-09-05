"""Render coverage registry rows into publishable Markdown summaries and priority queues."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from domains.campaign_finance.jurisdictions.refresh_registry import (
    load_validated_refresh_registrations,
)
from domains.campaign_finance.jurisdictions.config_schema import ConfigJurisdictionIdentity

from .registry import (
    DEFAULT_REGISTRY_PATH,
    _MUNICIPALITY_TYPE,
    _STATE_EQUIVALENT_TYPES,
    CoverageJurisdictionIdentity,
    CoverageRegistry,
    CoverageRegistryRow,
    IdentityTranslationError,
    IdentityTranslationMultipleError,
    IdentityTranslationNotFoundError,
    ScopedIdentity,
    load_registry,
    translate_identity,
)
from .seed_registry import build_fec_registry_row, derive_state_registry_rows

_DEFAULT_SUMMARY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "coverage-registry-summary.md"
)
_DEFAULT_QUEUE_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "coverage-build-priority-queue.md"
)
_DEFAULT_MATRIX_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "2026-launch-support-matrix.md"
)
_DEFAULT_JURISDICTIONS_ROOT = Path(__file__).resolve().parents[1] / "jurisdictions"
_REGISTRY_AUTHORITY_NOTE = (
    "Filing-authority decision source of truth: `docs/reference/research/coverage-registry.json`."
)
_TIER_SORT_ORDER = {
    "launch-support candidate": 0,
    "implemented but unproven": 1,
    "freshness-limited": 2,
    "deferred/blocked": 3,
    None: 4,
}
_AUTHORITY_RELATION_SORT_ORDER = {
    "partitioned_overlapping": 0,
    "independent": 1,
    "inherited": 2,
    "unresolved": 3,
}
_CADENCE_SORT_ORDER = {
    "continuous": 0,
    "daily": 1,
    "weekly": 2,
    "monthly": 3,
    "quarterly": 4,
    "annual": 5,
}


@dataclass(frozen=True, slots=True)
class CoveragePublicationMarkdown:
    summary_markdown: str
    queue_markdown: str
    matrix_markdown: str


@dataclass(frozen=True, slots=True)
class _PartitionedRegistryRows:
    state_rows: list[CoverageRegistryRow]
    county_rows: list[CoverageRegistryRow]
    municipality_rows: list[CoverageRegistryRow]
    school_district_rows: list[CoverageRegistryRow]
    special_district_rows: list[CoverageRegistryRow]

    @property
    def publishable_rows(self) -> list[CoverageRegistryRow]:
        return [
            *self.state_rows,
            *self.county_rows,
            *self.municipality_rows,
            *self.school_district_rows,
            *self.special_district_rows,
        ]


def coverage_identity_for_config_identity(
    config_identity: ConfigJurisdictionIdentity,
    *,
    registry: CoverageRegistry | None = None,
) -> CoverageJurisdictionIdentity:
    """Translate one composite config identity to its explicit coverage identity."""

    if config_identity[0] == "state":
        return config_identity
    resolved_registry = registry or load_registry(DEFAULT_REGISTRY_PATH)
    source = ScopedIdentity(
        domain="acquisition_scope",
        kind=config_identity[0],
        value=config_identity[1],
    )
    target = translate_identity(
        source,
        target_domain="geographic_subject",
        translations=resolved_registry.identity_translations,
    )
    registry_matches = [
        row
        for row in resolved_registry.rows
        if row.jurisdiction_type == target.kind and row.jurisdiction_code == target.value
    ]
    if not registry_matches:
        raise IdentityTranslationNotFoundError(
            f"typed coverage target has zero registry rows for {target.kind}/{target.value}"
        )
    if len(registry_matches) > 1:
        raise IdentityTranslationMultipleError(
            f"typed coverage target requires exactly one registry row for {target.kind}/{target.value}"
        )
    return target.kind, target.value


def config_identity_for_coverage_identity(
    coverage_identity: CoverageJurisdictionIdentity,
    *,
    registry: CoverageRegistry | None = None,
) -> ConfigJurisdictionIdentity:
    """Reverse only a proven state or explicit municipality coverage translation."""

    resolved_registry = registry or load_registry(DEFAULT_REGISTRY_PATH)
    if coverage_identity[0] == "state":
        return coverage_identity_for_config_identity(
            coverage_identity,
            registry=resolved_registry,
        )
    source = ScopedIdentity(
        domain="geographic_subject",
        kind=coverage_identity[0],
        value=coverage_identity[1],
    )
    target = translate_identity(
        source,
        target_domain="acquisition_scope",
        translations=resolved_registry.identity_translations,
    )
    return target.kind, target.value


def _partition_registry_rows(
    rows: list[CoverageRegistryRow],
) -> _PartitionedRegistryRows:
    """Split registry rows into every supported geographic-subject layer."""
    state_rows: list[CoverageRegistryRow] = []
    county_rows: list[CoverageRegistryRow] = []
    municipality_rows: list[CoverageRegistryRow] = []
    school_district_rows: list[CoverageRegistryRow] = []
    special_district_rows: list[CoverageRegistryRow] = []
    for row in rows:
        if row.jurisdiction_type in _STATE_EQUIVALENT_TYPES:
            state_rows.append(row)
            continue
        target = {
            "county": county_rows,
            "municipality": municipality_rows,
            "school_district": school_district_rows,
            "special_district": special_district_rows,
        }[row.jurisdiction_type]
        target.append(row)

    return _PartitionedRegistryRows(
        state_rows=state_rows,
        county_rows=county_rows,
        municipality_rows=municipality_rows,
        school_district_rows=school_district_rows,
        special_district_rows=special_district_rows,
    )


def _normalize_tier(tier: str | None) -> str:
    return tier if tier is not None else "unassigned"


def _normalize_next_action(next_action: str | None) -> str:
    return next_action if next_action is not None else ""


def _normalize_runner_wired(runner_wired: bool) -> str:
    return "yes" if runner_wired else "no"


def _normalize_municipal_decision(row: CoverageRegistryRow) -> str:
    return row.municipal_audit_decision or "not_applicable"


def _normalize_authority_relation(row: CoverageRegistryRow) -> str:
    return row.authority_relation.relation


def _authority_reference_label(row: CoverageRegistryRow) -> str:
    relation = row.authority_relation
    if relation.relation in {"independent", "inherited"}:
        authorities = [relation.authority]
    elif relation.relation == "partitioned_overlapping":
        authorities = relation.authorities
    else:
        authorities = relation.candidate_authorities
    labels = [
        f"{authority.kind}/{authority.code}" + (f" ({authority.name})" if authority.name is not None else "")
        for authority in authorities
    ]
    return ", ".join(labels) if labels else "unresolved"


def _queue_sort_key(row: CoverageRegistryRow) -> tuple[int, int, int, int, str, str]:
    return (
        _TIER_SORT_ORDER.get(row.tier, len(_TIER_SORT_ORDER)),
        0 if row.runner_wired else 1,
        _AUTHORITY_RELATION_SORT_ORDER.get(
            row.authority_relation.relation,
            len(_AUTHORITY_RELATION_SORT_ORDER),
        ),
        _CADENCE_SORT_ORDER.get(row.best_update_frequency, len(_CADENCE_SORT_ORDER)),
        _normalize_next_action(row.next_action).casefold(),
        row.jurisdiction_code,
    )


def _resolve_publication_date(rows: list[CoverageRegistryRow]) -> str:
    for candidate_dates in (
        [row.evidence_date for row in rows if row.evidence_date is not None],
        [row.best_last_verified_working for row in rows if row.best_last_verified_working is not None],
    ):
        if candidate_dates:
            return max(candidate_dates).isoformat()
    return "unknown"


def _publication_header_lines(title: str, publication_date: str, description: str) -> list[str]:
    return [
        title,
        "",
        f"Date: {publication_date}",
        "",
        _REGISTRY_AUTHORITY_NOTE,
        description,
        "",
    ]


def _render_state_table(rows: list[CoverageRegistryRow]) -> list[str]:
    return _render_table(
        header="| Jurisdiction | Authority Relation | Filing Authority | Tier | Best Cadence | Runner Wired | Source Count |",
        divider="| --- | --- | --- | --- | --- | --- | --- |",
        body_rows=[
            f"| {row.jurisdiction_code} | {_normalize_authority_relation(row)} | "
            f"{_authority_reference_label(row)} | {_normalize_tier(row.tier)} | {row.best_update_frequency} | "
            f"{_normalize_runner_wired(row.runner_wired)} | {row.source_count} |"
            for row in _sorted_rows_by_code(rows)
        ],
    )


def _render_municipality_table(rows: list[CoverageRegistryRow]) -> list[str]:
    return _render_table(
        header=(
            "| Jurisdiction | Parent | Authority Relation | Compatibility Decision | Filing Authority | "
            "Tier | Best Cadence | Source Count |"
        ),
        divider="| --- | --- | --- | --- | --- | --- | --- | --- |",
        body_rows=[
            f"| {row.jurisdiction_code} | {row.parent_jurisdiction_code or ''} | "
            f"{_normalize_authority_relation(row)} | {row.municipal_audit_decision or ''} | "
            f"{_authority_reference_label(row)} | {_normalize_tier(row.tier)} | "
            f"{row.best_update_frequency} | {row.source_count} |"
            for row in _sorted_rows_by_code(rows)
        ],
    )


def _render_local_authority_table(rows: list[CoverageRegistryRow]) -> list[str]:
    return _render_table(
        header="| Jurisdiction | Authority Relation | Filing Authority | Tier | Best Cadence | Source Count |",
        divider="| --- | --- | --- | --- | --- | --- |",
        body_rows=[
            f"| {row.jurisdiction_code} | {_normalize_authority_relation(row)} | "
            f"{_authority_reference_label(row)} | {_normalize_tier(row.tier)} | "
            f"{row.best_update_frequency} | {row.source_count} |"
            for row in _sorted_rows_by_code(rows)
        ],
    )


def _sorted_rows_by_code(rows: list[CoverageRegistryRow]) -> list[CoverageRegistryRow]:
    return sorted(rows, key=lambda row: row.jurisdiction_code)


def _render_table(*, header: str, divider: str, body_rows: list[str]) -> list[str]:
    return [header, divider, *body_rows]


def render_summary_markdown(
    registry: CoverageRegistry,
    *,
    publication_date: str | None = None,
) -> str:
    """Render the registry into a Markdown summary table grouped by jurisdiction layer."""
    partitioned_rows = _partition_registry_rows(registry.rows)
    resolved_publication_date = publication_date or _resolve_publication_date(registry.rows)

    lines = _publication_header_lines(
        "# Coverage Registry Summary (Derived)",
        resolved_publication_date,
        "This summary is a derived view of the full coverage registry.",
    )

    if partitioned_rows.state_rows or not partitioned_rows.publishable_rows:
        lines.append("## State / Federal Layer")
        lines.append("")
        lines.extend(_render_state_table(partitioned_rows.state_rows))

    if partitioned_rows.municipality_rows:
        lines.append("")
        lines.append("## Municipality Layer")
        lines.append("")
        lines.extend(_render_municipality_table(partitioned_rows.municipality_rows))

    for title, local_rows in (
        ("County", partitioned_rows.county_rows),
        ("School District", partitioned_rows.school_district_rows),
        ("Special District", partitioned_rows.special_district_rows),
    ):
        if not local_rows:
            continue
        lines.append("")
        lines.append(f"## {title} Layer")
        lines.append("")
        lines.extend(_render_local_authority_table(local_rows))

    return "\n".join(lines) + "\n"


def _render_queue_markdown(
    rows: list[CoverageRegistryRow],
    *,
    publication_date: str,
) -> str:
    """Render a deterministic build-priority queue table from registry rows."""
    lines = _publication_header_lines(
        "# Coverage Build Priority Queue (Derived)",
        publication_date,
        "This queue is generated from registry row fields only; update the registry, then rerun this publisher.",
    )
    lines.extend(
        [
            "Deterministic order uses `tier`, `runner_wired`, `authority_relation`,",
            "`best_update_frequency`, `next_action`, and `jurisdiction_code`.",
            "",
            "| Queue Group | Jurisdiction | Type | Runner Wired | Authority Relation | Compatibility Decision | Best Cadence | Next Action |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in sorted(rows, key=_queue_sort_key):
        lines.append(
            f"| {_normalize_tier(row.tier)} | {row.jurisdiction_code} | {row.jurisdiction_type} | "
            f"{_normalize_runner_wired(row.runner_wired)} | {_normalize_authority_relation(row)} | "
            f"{_normalize_municipal_decision(row)} | "
            f"{row.best_update_frequency} | {_normalize_next_action(row.next_action)} |"
        )
    return "\n".join(lines) + "\n"


def _render_matrix_markdown(
    rows: list[CoverageRegistryRow],
    *,
    implemented_jurisdiction_codes: set[str],
    publication_date: str,
) -> str:
    """Render a launch-support matrix filtered by canonical implemented membership."""
    matrix_rows = [row for row in rows if row.jurisdiction_code in implemented_jurisdiction_codes]

    lines = _publication_header_lines(
        "# 2026 Launch Support Matrix (Derived Implemented Packages)",
        publication_date,
        "This matrix is a derived view and is not an independent authority.",
    )
    lines.extend(
        [
            "Implemented package scope is derived from runtime discovery via",
            "`render_summary.derive_implemented_jurisdiction_codes()`.",
            "",
            "| Jurisdiction | Type | Authority Relation | Tier | Best Cadence | Runner Wired | Next Action |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in sorted(matrix_rows, key=_queue_sort_key):
        lines.append(
            f"| {row.jurisdiction_code} | {row.jurisdiction_type} | {_normalize_authority_relation(row)} | "
            f"{_normalize_tier(row.tier)} | "
            f"{row.best_update_frequency} | {_normalize_runner_wired(row.runner_wired)} | "
            f"{_normalize_next_action(row.next_action)} |"
        )
    return "\n".join(lines) + "\n"


def _registered_city_codes(jurisdictions_root: Path | None = None) -> set[str]:
    resolved_root = jurisdictions_root or _DEFAULT_JURISDICTIONS_ROOT
    return {
        code
        for jurisdiction_type, code in (item.identity for item in load_validated_refresh_registrations(resolved_root))
        if jurisdiction_type == _MUNICIPALITY_TYPE
    }


def _derive_implemented_city_jurisdiction_codes(
    *,
    configured_city_codes: Iterable[str] | None = None,
    supported_city_codes: Iterable[str] | None = None,
) -> set[str]:
    resolved_supported_city_codes = (
        _registered_city_codes() if supported_city_codes is None else set(supported_city_codes)
    )
    resolved_configured_city_codes = (
        resolved_supported_city_codes if configured_city_codes is None else set(configured_city_codes)
    )
    supported_config_codes = sorted(resolved_supported_city_codes & resolved_configured_city_codes)
    supported_config_identities: list[ConfigJurisdictionIdentity] = [
        ("municipality", code) for code in supported_config_codes
    ]
    missing_bridge_codes: list[str] = []
    resolved_coverage_identities: list[CoverageJurisdictionIdentity] = []
    for config_identity in supported_config_identities:
        try:
            resolved_coverage_identities.append(coverage_identity_for_config_identity(config_identity))
        except IdentityTranslationError:
            missing_bridge_codes.append(config_identity[1])
    if missing_bridge_codes:
        joined_codes = ", ".join(missing_bridge_codes)
        raise ValueError(f"Missing coverage-registry identity bridge for supported city config(s): {joined_codes}")
    return {coverage_identity[1] for coverage_identity in resolved_coverage_identities}


def derive_implemented_jurisdiction_codes() -> set[str]:
    identities = tuple(item.identity for item in load_validated_refresh_registrations(_DEFAULT_JURISDICTIONS_ROOT))
    # A configured state package remains implemented even when it is not wired
    # into the runner (currently Ohio). The registry owns runner composition;
    # the coverage registry continues to own package and public-claim scope.
    implemented_codes = {row.jurisdiction_code for row in derive_state_registry_rows(_DEFAULT_JURISDICTIONS_ROOT)}
    implemented_codes.add(build_fec_registry_row().jurisdiction_code)
    implemented_codes.update(
        _derive_implemented_city_jurisdiction_codes(
            configured_city_codes={
                code for jurisdiction_type, code in identities if jurisdiction_type == "municipality"
            },
            supported_city_codes={
                code for jurisdiction_type, code in identities if jurisdiction_type == "municipality"
            },
        )
    )
    return implemented_codes


def render_publication_markdown(
    registry: CoverageRegistry,
    *,
    implemented_jurisdiction_codes: set[str],
) -> CoveragePublicationMarkdown:
    """Produce all three derived Markdown artifacts from a single registry."""
    partitioned_rows = _partition_registry_rows(registry.rows)
    publication_date = _resolve_publication_date(registry.rows)
    return CoveragePublicationMarkdown(
        summary_markdown=render_summary_markdown(
            registry,
            publication_date=publication_date,
        ),
        queue_markdown=_render_queue_markdown(
            partitioned_rows.publishable_rows,
            publication_date=publication_date,
        ),
        matrix_markdown=_render_matrix_markdown(
            partitioned_rows.publishable_rows,
            implemented_jurisdiction_codes=implemented_jurisdiction_codes,
            publication_date=publication_date,
        ),
    )


def _write_markdown_file(path: Path, markdown: str) -> Path:
    output_path = path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the render-summary command."""
    parser = argparse.ArgumentParser(
        description="Render derived markdown coverage artifacts from coverage registry JSON"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Input path for coverage registry JSON",
    )
    parser.add_argument(
        "--summary-output",
        "--output",
        dest="summary_output",
        type=Path,
        default=_DEFAULT_SUMMARY_PATH,
        help="Output path for coverage summary markdown",
    )
    parser.add_argument(
        "--queue-output",
        type=Path,
        default=_DEFAULT_QUEUE_PATH,
        help="Output path for build-priority queue markdown",
    )
    parser.add_argument(
        "--matrix-output",
        type=Path,
        default=_DEFAULT_MATRIX_PATH,
        help="Output path for implemented-package matrix markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: load registry, render all Markdown artifacts, write to disk."""
    args = _build_argument_parser().parse_args(argv)
    try:
        registry = load_registry(args.path)
        publication = render_publication_markdown(
            registry,
            implemented_jurisdiction_codes=derive_implemented_jurisdiction_codes(),
        )
        summary_path = _write_markdown_file(args.summary_output, publication.summary_markdown)
        queue_path = _write_markdown_file(args.queue_output, publication.queue_markdown)
        matrix_path = _write_markdown_file(args.matrix_output, publication.matrix_markdown)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"Wrote registry summary markdown: {summary_path}")
    print(f"Wrote build-priority queue markdown: {queue_path}")
    print(f"Wrote launch-support matrix markdown: {matrix_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
