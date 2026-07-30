"""Measure employer-to-industry coverage over a deterministic FEC row sample."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
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
CUMULATIVE_TOP_LIMITS = (10, 25, 50, 100)

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


class EmployerAggregate(BaseModel):
    """Selected unknown non-junk rows grouped by canonical employer key."""

    model_config = ConfigDict(frozen=True)

    canonical_employer: str
    selected_row_count: int
    signed_net_amount: Decimal
    valid_amount_count: int
    rejected_amount_count: int
    raw_variant_counts: dict[str, int]


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
    unmapped_canonical_employer_counts: dict[str, int]
    unmapped_canonical_employer_aggregates: dict[str, EmployerAggregate]
    unknown_signed_net_amount: Decimal
    unknown_valid_amount_count: int
    unknown_rejected_amount_count: int
    junk_occupation_counts: dict[str, int]
    missing_junk_occupation_count: int

    @model_validator(mode="after")
    def validate_share_denominator_and_partition(self) -> CoverageMetrics:
        if self.selected_row_count == 0:
            raise ValueError("deterministic selection selected zero rows")
        if self.scanned_row_count < self.selected_row_count:
            raise ValueError("scanned row count cannot be smaller than selected row count")
        classified_count = self.junk_count + self.known_industry_count + self.unknown_non_junk_count
        if classified_count != self.selected_row_count:
            raise ValueError("employer classification counts must partition the selected rows")
        canonical_count = sum(self.unmapped_canonical_employer_counts.values())
        if canonical_count != self.unknown_non_junk_count:
            raise ValueError("canonical employer counts must sum to unknown non-junk rows")
        amount_count = self.unknown_valid_amount_count + self.unknown_rejected_amount_count
        if amount_count != self.unknown_non_junk_count:
            raise ValueError("unknown amount validity counts must partition unknown non-junk rows")
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


@dataclass
class _CoverageAccumulator:
    scanned_row_count: int = 0
    selected_row_count: int = 0
    junk_count: int = 0
    known_industry_count: int = 0
    unknown_non_junk_count: int = 0
    raw_employers: set[str] = field(default_factory=set)
    canonical_employers: set[str] = field(default_factory=set)
    unmapped_raw_employers: Counter[str] = field(default_factory=Counter)
    aggregate_builders: dict[str, _EmployerAggregateBuilder] = field(default_factory=dict)
    junk_occupations: Counter[str] = field(default_factory=Counter)
    missing_junk_occupation_count: int = 0

    def add_source_row(
        self,
        source_row_index: int,
        row: EmployerRow,
        selection_rule: SelectionRule,
    ) -> None:
        self.scanned_row_count += 1
        if not source_row_is_selected(source_row_index, selection_rule):
            return
        self._add_selected_row(row)

    def _add_selected_row(self, row: EmployerRow) -> None:
        self.selected_row_count += 1
        raw_employer = row.get("EMPLOYER")
        canonical_employer = canonicalize_employer(raw_employer)

        if raw_employer is not None:
            self.raw_employers.add(raw_employer)
        if canonical_employer is not None:
            self.canonical_employers.add(canonical_employer)

        if is_junk_employer(raw_employer):
            self._add_junk_row(row)
        elif industry_for_employer(raw_employer) != UNKNOWN_INDUSTRY:
            self.known_industry_count += 1
        elif canonical_employer is not None:
            self._add_unknown_row(row, raw_employer, canonical_employer)

    def _add_junk_row(self, row: EmployerRow) -> None:
        self.junk_count += 1
        occupation = _source_evidence_text(row.get("OCCUPATION"))
        if occupation is None:
            self.missing_junk_occupation_count += 1
        else:
            self.junk_occupations[occupation] += 1

    def _add_unknown_row(
        self,
        row: EmployerRow,
        raw_employer: str | None,
        canonical_employer: str,
    ) -> None:
        self.unknown_non_junk_count += 1
        if raw_employer is not None:
            self.unmapped_raw_employers[raw_employer] += 1
        _accumulate_unknown_employer(
            self.aggregate_builders,
            canonical_employer=canonical_employer,
            raw_employer=raw_employer,
            raw_amount=row.get("TRANSACTION_AMT"),
        )

    def to_metrics(self) -> CoverageMetrics:
        canonical_aggregates = _build_canonical_aggregates(self.aggregate_builders)
        return CoverageMetrics(
            scanned_row_count=self.scanned_row_count,
            selected_row_count=self.selected_row_count,
            distinct_raw_employer_count=len(self.raw_employers),
            distinct_canonical_employer_count=len(self.canonical_employers),
            junk_count=self.junk_count,
            known_industry_count=self.known_industry_count,
            unknown_non_junk_count=self.unknown_non_junk_count,
            unmapped_raw_employer_counts=dict(self.unmapped_raw_employers),
            unmapped_canonical_employer_counts=_canonical_counts(canonical_aggregates),
            unmapped_canonical_employer_aggregates=canonical_aggregates,
            unknown_signed_net_amount=_unknown_signed_net_amount(canonical_aggregates),
            unknown_valid_amount_count=_unknown_valid_amount_count(canonical_aggregates),
            unknown_rejected_amount_count=_unknown_rejected_amount_count(canonical_aggregates),
            junk_occupation_counts=dict(self.junk_occupations),
            missing_junk_occupation_count=self.missing_junk_occupation_count,
        )


def accumulate_coverage_metrics(
    rows: Iterable[EmployerRow],
    selection_rule: SelectionRule,
) -> CoverageMetrics:
    """Stream rows once and accumulate exact metrics for the selected sample."""
    accumulator = _CoverageAccumulator()
    for source_row_index, row in enumerate(rows):
        accumulator.add_source_row(source_row_index, row, selection_rule)
    return accumulator.to_metrics()


class _EmployerAggregateBuilder:
    def __init__(self, canonical_employer: str) -> None:
        self.canonical_employer = canonical_employer
        self.selected_row_count = 0
        self.signed_net_amount = Decimal("0")
        self.valid_amount_count = 0
        self.rejected_amount_count = 0
        self.raw_variant_counts: Counter[str] = Counter()

    def add_row(self, raw_employer: str | None, raw_amount: str | None) -> None:
        self.selected_row_count += 1
        if raw_employer is not None:
            self.raw_variant_counts[raw_employer] += 1

        amount = _parse_transaction_amount(raw_amount)
        if amount is None:
            self.rejected_amount_count += 1
        else:
            self.valid_amount_count += 1
            self.signed_net_amount += amount

    def to_aggregate(self) -> EmployerAggregate:
        return EmployerAggregate(
            canonical_employer=self.canonical_employer,
            selected_row_count=self.selected_row_count,
            signed_net_amount=self.signed_net_amount,
            valid_amount_count=self.valid_amount_count,
            rejected_amount_count=self.rejected_amount_count,
            raw_variant_counts=dict(self.raw_variant_counts),
        )


def _accumulate_unknown_employer(
    aggregate_builders: dict[str, _EmployerAggregateBuilder],
    *,
    canonical_employer: str,
    raw_employer: str | None,
    raw_amount: str | None,
) -> None:
    builder = aggregate_builders.setdefault(
        canonical_employer,
        _EmployerAggregateBuilder(canonical_employer),
    )
    builder.add_row(raw_employer, raw_amount)


def _build_canonical_aggregates(
    aggregate_builders: Mapping[str, _EmployerAggregateBuilder],
) -> dict[str, EmployerAggregate]:
    return {canonical_employer: builder.to_aggregate() for canonical_employer, builder in aggregate_builders.items()}


def _canonical_counts(
    canonical_aggregates: Mapping[str, EmployerAggregate],
) -> dict[str, int]:
    return {
        canonical_employer: aggregate.selected_row_count
        for canonical_employer, aggregate in canonical_aggregates.items()
    }


def _unknown_valid_amount_count(
    canonical_aggregates: Mapping[str, EmployerAggregate],
) -> int:
    return sum(item.valid_amount_count for item in canonical_aggregates.values())


def _unknown_rejected_amount_count(
    canonical_aggregates: Mapping[str, EmployerAggregate],
) -> int:
    return sum(item.rejected_amount_count for item in canonical_aggregates.values())


def _unknown_signed_net_amount(
    canonical_aggregates: Mapping[str, EmployerAggregate],
) -> Decimal:
    return sum(
        (item.signed_net_amount for item in canonical_aggregates.values()),
        Decimal("0"),
    )


def _parse_transaction_amount(raw_amount: str | None) -> Decimal | None:
    amount_text = _source_evidence_text(raw_amount)
    if amount_text is None:
        return None
    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _source_evidence_text(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    stripped_value = raw_value.strip()
    return stripped_value or None


def rank_top_unmapped_employers(
    employer_aggregates: Mapping[str, EmployerAggregate],
    *,
    limit: int,
) -> tuple[EmployerAggregate, ...]:
    """Rank canonical employers by descending selected rows and lexical tie-break."""
    _validate_top_unmapped_limit(limit)
    ranked_aggregates = sorted(
        employer_aggregates.values(),
        key=lambda item: (-item.selected_row_count, item.canonical_employer),
    )
    return tuple(ranked_aggregates[:limit])


def _validate_top_unmapped_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("top-unmapped limit must be greater than zero")


def _render_share(label: str, numerator: int, denominator: int) -> str:
    if denominator <= 0:
        raise ValueError(f"{label} denominator must be greater than zero")
    percentage = numerator / denominator * 100
    return f"- {label}: **{percentage:.6f}%** ({numerator:,} / {denominator:,})"


def _render_percentage(numerator: int | Decimal, denominator: int | Decimal) -> str:
    if denominator == 0:
        return "NOT_COMPUTABLE"
    percentage = Decimal(numerator) / Decimal(denominator) * Decimal("100")
    return f"{percentage:.6f}%"


def _render_decimal(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def render_markdown_receipt(
    metadata: ReceiptMetadata,
    selection_rule: SelectionRule,
    metrics: CoverageMetrics,
    *,
    top_limit: int,
) -> str:
    """Render a complete reproducibility and metric receipt."""
    neutralize_untrusted_text = _markdown_neutralizer()
    _validate_top_unmapped_limit(top_limit)
    ranked_for_receipt = rank_top_unmapped_employers(
        metrics.unmapped_canonical_employer_aggregates,
        limit=max(top_limit, max(CUMULATIVE_TOP_LIMITS)),
    )
    ranked_top_100 = ranked_for_receipt[: max(CUMULATIVE_TOP_LIMITS)]
    top_unmapped = ranked_for_receipt[:top_limit]
    top_lines = _render_top_employer_table(top_unmapped, neutralize_untrusted_text)
    cumulative_lines = _render_cumulative_frames(ranked_top_100, metrics)
    occupation_lines = _render_junk_occupation_distribution(metrics, neutralize_untrusted_text)
    pool_distribution = _pool_distribution(ranked_top_100, metrics.unknown_non_junk_count)

    lines = [
        "# Employer industry coverage random baseline",
        "",
        *_render_receipt_header(metadata, selection_rule, neutralize_untrusted_text),
        *_render_metric_summary(metrics),
        "All three shares use the selected-row sample as their denominator. The unknown numerator excludes junk rows.",
        "",
        _render_signed_net_denominator(metrics),
        "",
        "## Cumulative canonical employer concentration",
        "",
        *cumulative_lines,
        "",
        f"POOL_DISTRIBUTION: {pool_distribution}",
        "",
        f"## Top {top_limit} unmapped non-junk employers",
        "",
        "Counts are canonical employer-key frequencies, sorted by descending count with lexical tie-breaks.",
        "",
        *top_lines,
        "",
        "## Junk occupation distribution",
        "",
        *occupation_lines,
        "",
        "No third-party service participated in this read-only local measurement.",
        "",
    ]
    return "\n".join(lines)


def _markdown_neutralizer() -> Callable[[object], str]:
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
            "(": "&#40;",
            ")": "&#41;",
            "\r": " ",
            "\n": " ",
            "\u2028": " ",
            "\u2029": " ",
        }
    )
    return lambda value: str(value).translate(markdown_neutralization)


def _render_receipt_header(
    metadata: ReceiptMetadata,
    selection_rule: SelectionRule,
    neutralize_untrusted_text: Callable[[object], str],
) -> list[str]:
    return [
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
    ]


def _render_metric_summary(metrics: CoverageMetrics) -> list[str]:
    return [
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
    ]


def _render_signed_net_denominator(metrics: CoverageMetrics) -> str:
    return (
        "UNKNOWN_POOL_SIGNED_NET_DENOMINATOR: "
        f"{_render_decimal(metrics.unknown_signed_net_amount)} "
        f"(valid_amount_rows={metrics.unknown_valid_amount_count:,}; "
        f"rejected_amount_rows={metrics.unknown_rejected_amount_count:,})"
    )


def _render_top_employer_table(
    top_unmapped: tuple[EmployerAggregate, ...],
    neutralize_untrusted_text: Callable[[object], str],
) -> list[str]:
    if not top_unmapped:
        return ["No unknown non-junk employers were selected."]

    lines = [
        "| Rank | Canonical employer key | Selected rows | Valid amount rows | "
        "Rejected amount rows | Signed net amount | Raw variants |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for rank, aggregate in enumerate(top_unmapped, start=1):
        variants = _render_raw_variants(aggregate.raw_variant_counts, neutralize_untrusted_text)
        lines.append(
            f"| {rank} | {neutralize_untrusted_text(aggregate.canonical_employer)} | "
            f"{aggregate.selected_row_count:,} | {aggregate.valid_amount_count:,} | "
            f"{aggregate.rejected_amount_count:,} | {_render_decimal(aggregate.signed_net_amount)} | "
            f"{variants} |"
        )
    return lines


def _render_raw_variants(
    variant_counts: Mapping[str, int],
    neutralize_untrusted_text: Callable[[object], str],
) -> str:
    ranked_variants = sorted(variant_counts.items(), key=lambda item: (-item[1], item[0]))
    return "; ".join(f"{neutralize_untrusted_text(raw_employer)}: {count:,}" for raw_employer, count in ranked_variants)


def _render_cumulative_frames(
    ranked_top_100: tuple[EmployerAggregate, ...],
    metrics: CoverageMetrics,
) -> list[str]:
    cumulative_lines = []
    for top_limit in CUMULATIVE_TOP_LIMITS:
        selected_aggregates = ranked_top_100[:top_limit]
        row_numerator = sum(item.selected_row_count for item in selected_aggregates)
        amount_numerator = sum((item.signed_net_amount for item in selected_aggregates), Decimal("0"))
        cumulative_lines.append(_render_cumulative_frame(top_limit, row_numerator, amount_numerator, metrics))
    return cumulative_lines


def _render_cumulative_frame(
    top_limit: int,
    row_numerator: int,
    amount_numerator: Decimal,
    metrics: CoverageMetrics,
) -> str:
    row_share = _render_percentage(row_numerator, metrics.unknown_non_junk_count)
    amount_share = _render_percentage(amount_numerator, metrics.unknown_signed_net_amount)
    return (
        f"CUMULATIVE_SHARE_TOP_{top_limit}: rows={row_numerator:,} / "
        f"{metrics.unknown_non_junk_count:,}; row_share={row_share}; "
        f"signed_net={_render_decimal(amount_numerator)} / "
        f"{_render_decimal(metrics.unknown_signed_net_amount)}; signed_net_share={amount_share}"
    )


def _pool_distribution(
    ranked_top_100: tuple[EmployerAggregate, ...],
    unknown_non_junk_count: int,
) -> str:
    if unknown_non_junk_count == 0:
        return "LONG_TAILED"
    top_100_count = sum(item.selected_row_count for item in ranked_top_100[:100])
    if top_100_count * 2 >= unknown_non_junk_count:
        return "HEAD_HEAVY"
    return "LONG_TAILED"


def _render_junk_occupation_distribution(
    metrics: CoverageMetrics,
    neutralize_untrusted_text: Callable[[object], str],
) -> list[str]:
    if not metrics.junk_occupation_counts:
        occupation_lines = ["No junk occupations were supplied."]
    else:
        occupation_lines = [
            f"- {neutralize_untrusted_text(occupation)}: {count:,}"
            for occupation, count in sorted(
                metrics.junk_occupation_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
    occupation_lines.append(f"- Missing or blank junk occupation rows: {metrics.missing_junk_occupation_count:,}")
    return occupation_lines


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
