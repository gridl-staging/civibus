"""Measure employer-to-industry coverage over a deterministic FEC row sample."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
import hashlib
from pathlib import Path
import platform

from pydantic import BaseModel, ConfigDict, model_validator

from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.fec_bulk_files import (
    fec_bulk_data_cache_path,
    resolve_fec_data_root,
)
from domains.campaign_finance.normalize.employers import (
    UNKNOWN_INDUSTRY,
    canonicalize_employer,
    industry_for_employer,
    is_junk_employer,
)

DEFAULT_ARCHIVE_CYCLE = 2024
DEFAULT_SELECTION_SEED = 20260727
DEFAULT_SELECTION_MODULUS = 4096
DEFAULT_TARGET_BUCKET = 0
DEFAULT_TOP_LIMIT = 20
DEFAULT_OUTPUT_PATH = Path("docs/live-state/2026_07_27_employer_industry_coverage.md")

EmployerRow = Mapping[str, str | None]


class SelectionRule(BaseModel):
    """Deterministic row-index hash selection parameters."""

    model_config = ConfigDict(frozen=True)

    seed: int
    modulus: int
    target_bucket: int

    @model_validator(mode="after")
    def validate_bucket(self) -> SelectionRule:
        if self.modulus <= 0:
            raise ValueError("modulus must be greater than zero")
        if not 0 <= self.target_bucket < self.modulus:
            raise ValueError("target_bucket must be between zero and modulus minus one")
        return self


class EmployerFrequency(BaseModel):
    """An unmapped raw employer and its selected-row frequency."""

    model_config = ConfigDict(frozen=True)

    raw_employer: str
    count: int


class CoverageMetrics(BaseModel):
    """Counts required by the employer-industry coverage receipt."""

    model_config = ConfigDict(frozen=True)

    scanned_row_count: int
    selected_row_count: int
    distinct_raw_employer_count: int
    distinct_canonical_employer_count: int
    junk_count: int
    known_industry_count: int
    unknown_non_junk_count: int
    unmapped_raw_employer_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_share_denominator_and_partition(self) -> CoverageMetrics:
        if self.selected_row_count == 0:
            raise ValueError("deterministic selection selected zero rows")
        if self.scanned_row_count < self.selected_row_count:
            raise ValueError("scanned row count cannot be smaller than selected row count")
        classified_count = self.junk_count + self.known_industry_count + self.unknown_non_junk_count
        if classified_count != self.selected_row_count:
            raise ValueError("employer classification counts must partition the selected rows")
        return self


class ReceiptMetadata(BaseModel):
    """Execution and archive identity rendered into the receipt."""

    model_config = ConfigDict(frozen=True)

    archive_cycle: int
    archive_path: Path
    execution_locality: str


def source_row_is_selected(source_row_index: int, selection_rule: SelectionRule) -> bool:
    """Select a row using only its zero-based source index and a fixed rule."""
    selection_key = f"{selection_rule.seed}:{source_row_index}".encode()
    hash_value = int.from_bytes(hashlib.sha256(selection_key).digest(), byteorder="big")
    return hash_value % selection_rule.modulus == selection_rule.target_bucket


def iter_selected_rows(
    rows: Iterable[EmployerRow],
    selection_rule: SelectionRule,
) -> Iterator[tuple[int, EmployerRow]]:
    """Yield selected source rows lazily with their zero-based indexes."""
    for source_row_index, row in enumerate(rows):
        if source_row_is_selected(source_row_index, selection_rule):
            yield source_row_index, row


def accumulate_coverage_metrics(
    rows: Iterable[EmployerRow],
    selection_rule: SelectionRule,
) -> CoverageMetrics:
    """Stream rows once and accumulate exact metrics for the selected sample."""
    scanned_row_count = 0
    selected_row_count = 0
    junk_count = 0
    known_industry_count = 0
    unknown_non_junk_count = 0
    raw_employers: set[str] = set()
    canonical_employers: set[str] = set()
    unmapped_raw_employers: Counter[str] = Counter()

    for source_row_index, row in enumerate(rows):
        scanned_row_count += 1
        if not source_row_is_selected(source_row_index, selection_rule):
            continue

        selected_row_count += 1
        raw_employer = row.get("EMPLOYER")
        canonical_employer = canonicalize_employer(raw_employer)
        industry = industry_for_employer(raw_employer)
        junk = is_junk_employer(raw_employer)

        if raw_employer is not None:
            raw_employers.add(raw_employer)
        if canonical_employer is not None:
            canonical_employers.add(canonical_employer)

        if junk:
            junk_count += 1
        elif industry != UNKNOWN_INDUSTRY:
            known_industry_count += 1
        else:
            unknown_non_junk_count += 1
            if raw_employer is not None:
                unmapped_raw_employers[raw_employer] += 1

    return CoverageMetrics(
        scanned_row_count=scanned_row_count,
        selected_row_count=selected_row_count,
        distinct_raw_employer_count=len(raw_employers),
        distinct_canonical_employer_count=len(canonical_employers),
        junk_count=junk_count,
        known_industry_count=known_industry_count,
        unknown_non_junk_count=unknown_non_junk_count,
        unmapped_raw_employer_counts=dict(unmapped_raw_employers),
    )


def rank_top_unmapped_employers(
    employer_counts: Mapping[str, int],
    *,
    limit: int,
) -> tuple[EmployerFrequency, ...]:
    """Rank raw employers by descending frequency and lexical tie-break."""
    if limit <= 0:
        raise ValueError("top-unmapped limit must be greater than zero")
    ranked_counts = sorted(employer_counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(
        EmployerFrequency(raw_employer=raw_employer, count=count) for raw_employer, count in ranked_counts[:limit]
    )


def _render_share(label: str, numerator: int, denominator: int) -> str:
    if denominator <= 0:
        raise ValueError(f"{label} denominator must be greater than zero")
    percentage = numerator / denominator * 100
    return f"- {label}: **{percentage:.6f}%** ({numerator:,} / {denominator:,})"


def render_markdown_receipt(
    metadata: ReceiptMetadata,
    selection_rule: SelectionRule,
    metrics: CoverageMetrics,
    *,
    top_limit: int,
) -> str:
    """Render a complete reproducibility and metric receipt."""
    markdown_neutralization = str.maketrans(
        {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "\\": "&#92;",
            "`": "&#96;",
            "*": "&#42;",
            "_": "&#95;",
            "[": "&#91;",
            "]": "&#93;",
            "\r": " ",
            "\n": " ",
            "\u2028": " ",
            "\u2029": " ",
        }
    )

    def neutralize_untrusted_text(value: object) -> str:
        return str(value).translate(markdown_neutralization)

    top_unmapped = rank_top_unmapped_employers(
        metrics.unmapped_raw_employer_counts,
        limit=top_limit,
    )
    top_lines = [
        f"{rank}. {neutralize_untrusted_text(item.raw_employer)}: {item.count:,}"
        for rank, item in enumerate(top_unmapped, start=1)
    ]
    if not top_lines:
        top_lines = ["No unknown non-junk employers were selected."]

    lines = [
        "# Employer industry coverage random baseline",
        "",
        f"Execution locality: `{neutralize_untrusted_text(metadata.execution_locality)}`",
        "",
        f"Archive cycle: `{metadata.archive_cycle}`",
        "",
        f"Archive path: `{neutralize_untrusted_text(metadata.archive_path)}`",
        "",
        "Selection rule: SHA-256 of "
        f"`{selection_rule.seed}:{{source_row_index}}` modulo `{selection_rule.modulus}` "
        f"equals target bucket `{selection_rule.target_bucket}`. Source row indexes are zero-based.",
        "",
        f"Fixed seed: `{selection_rule.seed}`",
        "",
        f"Selection modulus: `{selection_rule.modulus}`",
        "",
        f"Target bucket: `{selection_rule.target_bucket}`",
        "",
        f"Selected rows (sample size): **{metrics.selected_row_count:,}**",
        "",
        f"Scanned rows: **{metrics.scanned_row_count:,}**",
        "",
        f"- Distinct raw employer strings: **{metrics.distinct_raw_employer_count:,}**",
        f"- Distinct canonical employer keys: **{metrics.distinct_canonical_employer_count:,}**",
        _render_share("Junk employer share", metrics.junk_count, metrics.selected_row_count),
        _render_share("Known-industry share", metrics.known_industry_count, metrics.selected_row_count),
        _render_share("Unknown non-junk share", metrics.unknown_non_junk_count, metrics.selected_row_count),
        "",
        "All three shares use the selected-row sample as their denominator. The unknown numerator excludes junk rows.",
        "",
        f"## Top {top_limit} unmapped non-junk employers",
        "",
        "Counts are raw employer-string frequencies, sorted by descending count with lexical tie-breaks.",
        "",
        *top_lines,
        "",
        "No third-party service participated in this read-only local measurement.",
        "",
    ]
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line contract for the coverage receipt."""
    parser = argparse.ArgumentParser(
        description="Measure deterministic random employer-industry coverage over an existing FEC itcont archive."
    )
    parser.add_argument("--cycle", type=int, default=DEFAULT_ARCHIVE_CYCLE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SELECTION_SEED)
    parser.add_argument("--modulus", type=int, default=DEFAULT_SELECTION_MODULUS)
    parser.add_argument("--target-bucket", type=int, default=DEFAULT_TARGET_BUCKET)
    parser.add_argument("--top-limit", type=int, default=DEFAULT_TOP_LIMIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Measure the canonical archive and write the Markdown receipt."""
    arguments = build_argument_parser().parse_args(argv)
    selection_rule = SelectionRule(
        seed=arguments.seed,
        modulus=arguments.modulus,
        target_bucket=arguments.target_bucket,
    )
    data_root = resolve_fec_data_root()
    archive_path = fec_bulk_data_cache_path(data_root, cycle=arguments.cycle, file_type="itcont")
    if not archive_path.is_file():
        raise FileNotFoundError(f"FEC itcont archive does not exist: {archive_path}")

    rows = read_bulk_file(archive_path, "itcont", expected_member_name="itcont.txt")
    metrics = accumulate_coverage_metrics(rows, selection_rule)
    metadata = ReceiptMetadata(
        archive_cycle=arguments.cycle,
        archive_path=archive_path,
        execution_locality=platform.node(),
    )
    receipt = render_markdown_receipt(metadata, selection_rule, metrics, top_limit=arguments.top_limit)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(receipt, encoding="utf-8")
    print(
        f"Wrote {arguments.output} from {metrics.selected_row_count:,} selected "
        f"of {metrics.scanned_row_count:,} scanned rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
