"""Measure employer-to-industry coverage over a deterministic FEC row sample."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import math
from pathlib import Path
import platform
from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.fec_bulk_files import (
    fec_bulk_data_cache_path,
    resolve_fec_data_root,
)
from domains.campaign_finance.normalize.employers import (
    INDUSTRY_BY_EMPLOYER_MIN_COVERAGE,
    OCCUPATION_INDUSTRIES,
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
REQUIRED_DERIVED_COVERAGE_BAR = 1_104
STAGE_3_KNOWN_OR_DERIVED_COUNT = 837
STAGE_3_EXTERNAL_REFERENCE_DISPOSITION = "NO SOURCE SELECTED"
NON_INDUSTRY_SIGNAL_OCCUPATIONS = frozenset({"CONSULTANT", "EMPLOYED", "MANAGER", "OWNER", "STUDENT", "VOLUNTEER"})
STAGE_1_BASELINE = {
    "archive_cycle": DEFAULT_ARCHIVE_CYCLE,
    "selection_seed": DEFAULT_SELECTION_SEED,
    "selection_modulus": DEFAULT_SELECTION_MODULUS,
    "target_bucket": DEFAULT_TARGET_BUCKET,
    "scanned_row_count": 58_208_756,
    "selected_row_count": 14_324,
    "junk_count": 9_980,
    "known_industry_count": 370,
    "unknown_non_junk_count": 3_974,
    "selected_sample_digest": "6999f5676192c378abfc6baa2075de8594fbe8cf81818cfd2fa4529fd758c419",
}

EmployerRow = Mapping[str, str | None]


class _SampleHasher(Protocol):
    def update(self, data: bytes) -> None: ...
    def hexdigest(self) -> str: ...


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


class ReferenceEmployerRecord(BaseModel):
    """Observed external organization name and its source classification."""

    model_config = ConfigDict(frozen=True)

    organization_name: str | None
    classification_code: str | None


class ReferenceOverlapMetrics(BaseModel):
    """Overlap between classified reference names and the selected unknown pool."""

    model_config = ConfigDict(frozen=True)

    matched_selected_row_count: int
    matched_distinct_canonical_employer_count: int
    matched_canonical_employers: tuple[str, ...]


class ExternalReferenceCandidateDisposition(BaseModel):
    """Measured reach of a Stage 3 external-reference candidate."""

    model_config = ConfigDict(frozen=True)

    source_name: str
    matched_row_count: int
    match_frame: str

    @property
    def combined_row_count(self) -> int:
        return STAGE_3_KNOWN_OR_DERIVED_COUNT + self.matched_row_count

    @property
    def shortfall_row_count(self) -> int:
        minimum_passing_count = REQUIRED_DERIVED_COVERAGE_BAR + 1
        return minimum_passing_count - self.combined_row_count


class ExternalReferenceDispositionSampleIdentity(BaseModel):
    """Fixed Stage 3 sample identity attached to prior external-reference evidence."""

    model_config = ConfigDict(frozen=True)

    archive_cycle: int
    selection_seed: int
    selection_modulus: int
    target_bucket: int
    selected_sample_digest: str
    known_or_derived_count: int


STAGE_3_FIXED_SAMPLE_IDENTITY = ExternalReferenceDispositionSampleIdentity(
    archive_cycle=STAGE_1_BASELINE["archive_cycle"],
    selection_seed=STAGE_1_BASELINE["selection_seed"],
    selection_modulus=STAGE_1_BASELINE["selection_modulus"],
    target_bucket=STAGE_1_BASELINE["target_bucket"],
    selected_sample_digest=STAGE_1_BASELINE["selected_sample_digest"],
    known_or_derived_count=STAGE_3_KNOWN_OR_DERIVED_COUNT,
)


STAGE_3_REJECTED_REFERENCE_CANDIDATES = (
    ExternalReferenceCandidateDisposition(
        source_name="SEC/EDGAR",
        matched_row_count=197,
        match_frame="matched",
    ),
    ExternalReferenceCandidateDisposition(
        source_name="IRS EO BMF/NTEE",
        matched_row_count=188,
        match_frame="generous upper bound",
    ),
)


class CoverageCeilingSummary(BaseModel):
    """Stage 1 ceiling frame and current disjoint combined reach."""

    model_config = ConfigDict(frozen=True)

    selected_row_count: int
    known_industry_count: int
    occupation_top_limit: int
    occupation_ceiling_count: int
    external_reference_ceiling_count: int
    combined_ceiling_count: int
    required_bar_count: int
    clears_required_bar: bool

    @model_validator(mode="after")
    def validate_combined_ceiling(self) -> CoverageCeilingSummary:
        expected_combined = self.known_industry_count + self.external_reference_ceiling_count
        if self.combined_ceiling_count != expected_combined:
            raise ValueError("combined ceiling must equal known-or-derived + external reach")
        return self


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
    employer_only_junk_count: int
    employer_only_known_industry_count: int
    employer_only_unknown_non_junk_count: int
    occupation_derived_industry_count: int
    occupation_derived_rule_counts: dict[str, int]
    unmapped_raw_employer_counts: dict[str, int]
    unmapped_canonical_employer_counts: dict[str, int]
    unmapped_canonical_employer_aggregates: dict[str, EmployerAggregate]
    unknown_signed_net_amount: Decimal
    unknown_valid_amount_count: int
    unknown_rejected_amount_count: int
    junk_occupation_counts: dict[str, int]
    missing_junk_occupation_count: int
    selected_nonempty_occupation_count: int
    selected_blank_occupation_count: int
    selected_junk_equivalent_occupation_count: int
    selected_occupation_counts: dict[str, int]
    occupation_ceiling_candidate_counts: dict[str, int]
    selected_sample_digest: str

    @model_validator(mode="after")
    def validate_share_denominator_and_partition(self) -> CoverageMetrics:
        if self.selected_row_count == 0:
            raise ValueError("deterministic selection selected zero rows")
        if self.scanned_row_count < self.selected_row_count:
            raise ValueError("scanned row count cannot be smaller than selected row count")
        classified_count = self.junk_count + self.known_industry_count + self.unknown_non_junk_count
        if classified_count != self.selected_row_count:
            raise ValueError("employer classification counts must partition the selected rows")
        employer_only_count = (
            self.employer_only_junk_count
            + self.employer_only_known_industry_count
            + self.employer_only_unknown_non_junk_count
        )
        if employer_only_count != self.selected_row_count:
            raise ValueError("employer-only baseline counts must partition the selected rows")
        expected_known = self.employer_only_known_industry_count + self.occupation_derived_industry_count
        if self.known_industry_count != expected_known:
            raise ValueError("known industry count must equal employer-only known plus occupation-derived rows")
        if sum(self.occupation_derived_rule_counts.values()) != self.occupation_derived_industry_count:
            raise ValueError("occupation rule counts must sum to occupation-derived rows")
        canonical_count = sum(self.unmapped_canonical_employer_counts.values())
        if canonical_count != self.unknown_non_junk_count:
            raise ValueError("canonical employer counts must sum to unknown non-junk rows")
        amount_count = self.unknown_valid_amount_count + self.unknown_rejected_amount_count
        if amount_count != self.unknown_non_junk_count:
            raise ValueError("unknown amount validity counts must partition unknown non-junk rows")
        occupation_count = self.selected_nonempty_occupation_count + self.selected_blank_occupation_count
        if occupation_count != self.selected_row_count:
            raise ValueError("occupation presence counts must partition selected rows")
        counted_occupations = sum(self.selected_occupation_counts.values())
        if counted_occupations != self.selected_nonempty_occupation_count:
            raise ValueError("selected occupation counts must sum to non-empty occupation rows")
        ceiling_occupations = sum(self.occupation_ceiling_candidate_counts.values())
        if ceiling_occupations > self.employer_only_junk_count:
            raise ValueError("occupation ceiling candidates cannot exceed employer-only junk rows")
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


def iter_selected_rows(rows: Iterable[EmployerRow], selection_rule: SelectionRule) -> Iterator[tuple[int, EmployerRow]]:
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
    employer_only_junk_count: int = 0
    employer_only_known_industry_count: int = 0
    employer_only_unknown_non_junk_count: int = 0
    occupation_derived_industry_count: int = 0
    occupation_derived_rules: Counter[str] = field(default_factory=Counter)
    raw_employers: set[str] = field(default_factory=set)
    canonical_employers: set[str] = field(default_factory=set)
    unmapped_raw_employers: Counter[str] = field(default_factory=Counter)
    aggregate_builders: dict[str, _EmployerAggregateBuilder] = field(default_factory=dict)
    junk_occupations: Counter[str] = field(default_factory=Counter)
    missing_junk_occupation_count: int = 0
    selected_occupations: Counter[str] = field(default_factory=Counter)
    selected_blank_occupation_count: int = 0
    selected_junk_equivalent_occupation_count: int = 0
    occupation_ceiling_candidates: Counter[str] = field(default_factory=Counter)
    selected_sample_hasher: _SampleHasher = field(default_factory=hashlib.sha256)

    def add_source_row(
        self,
        source_row_index: int,
        row: EmployerRow,
        selection_rule: SelectionRule,
    ) -> None:
        self.scanned_row_count += 1
        if not source_row_is_selected(source_row_index, selection_rule):
            return
        _update_selected_sample_digest(self.selected_sample_hasher, source_row_index, row)
        self._add_selected_row(row)

    def _add_selected_row(self, row: EmployerRow) -> None:
        self.selected_row_count += 1
        raw_employer = row.get("EMPLOYER")
        canonical_employer = canonicalize_employer(raw_employer)
        occupation = _source_evidence_text(row.get("OCCUPATION"))
        self._add_selected_occupation(occupation)
        if raw_employer is not None:
            self.raw_employers.add(raw_employer)
        if canonical_employer is not None:
            self.canonical_employers.add(canonical_employer)

        employer_only_industry = industry_for_employer(raw_employer)
        employer_only_junk = is_junk_employer(raw_employer)
        self._add_employer_only_baseline_row(raw_employer, canonical_employer, occupation, employer_only_industry)

        derived_industry = industry_for_employer(raw_employer, occupation=occupation)
        if derived_industry != UNKNOWN_INDUSTRY:
            self.known_industry_count += 1
            if employer_only_industry == UNKNOWN_INDUSTRY:
                self.occupation_derived_industry_count += 1
                canonical_occupation = canonicalize_employer(occupation)
                if canonical_occupation is not None:
                    self.occupation_derived_rules[canonical_occupation] += 1
        elif employer_only_junk:
            self.junk_count += 1
        elif canonical_employer is not None:
            self._add_unknown_row(row, raw_employer, canonical_employer)

    def _add_selected_occupation(self, occupation: str | None) -> None:
        if occupation is None:
            self.selected_blank_occupation_count += 1
            return
        self.selected_occupations[occupation] += 1
        if _occupation_is_junk_equivalent(occupation):
            self.selected_junk_equivalent_occupation_count += 1

    def _add_employer_only_baseline_row(
        self,
        raw_employer: str | None,
        canonical_employer: str | None,
        occupation: str | None,
        employer_only_industry: str,
    ) -> None:
        if is_junk_employer(raw_employer):
            self.employer_only_junk_count += 1
            self._add_junk_occupation_evidence(occupation)
        elif employer_only_industry != UNKNOWN_INDUSTRY:
            self.employer_only_known_industry_count += 1
        elif canonical_employer is not None:
            self.employer_only_unknown_non_junk_count += 1

    def _add_junk_occupation_evidence(self, occupation: str | None) -> None:
        if occupation is None:
            self.missing_junk_occupation_count += 1
        else:
            self.junk_occupations[occupation] += 1
            if not _occupation_is_junk_equivalent(occupation):
                canonical_occupation = canonicalize_employer(occupation)
                if canonical_occupation is not None:
                    self.occupation_ceiling_candidates[canonical_occupation] += 1

    def _add_unknown_row(
        self,
        row: EmployerRow,
        raw_employer: str | None,
        canonical_employer: str,
    ) -> None:
        self.unknown_non_junk_count += 1
        if raw_employer is not None:
            self.unmapped_raw_employers[raw_employer] += 1
        builder = self.aggregate_builders.setdefault(
            canonical_employer,
            _EmployerAggregateBuilder(canonical_employer),
        )
        builder.add_row(raw_employer, row.get("TRANSACTION_AMT"))

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
            employer_only_junk_count=self.employer_only_junk_count,
            employer_only_known_industry_count=self.employer_only_known_industry_count,
            employer_only_unknown_non_junk_count=self.employer_only_unknown_non_junk_count,
            occupation_derived_industry_count=self.occupation_derived_industry_count,
            occupation_derived_rule_counts=dict(self.occupation_derived_rules),
            unmapped_raw_employer_counts=dict(self.unmapped_raw_employers),
            unmapped_canonical_employer_counts={
                employer: aggregate.selected_row_count for employer, aggregate in canonical_aggregates.items()
            },
            unmapped_canonical_employer_aggregates=canonical_aggregates,
            unknown_signed_net_amount=sum(
                (aggregate.signed_net_amount for aggregate in canonical_aggregates.values()), Decimal("0")
            ),
            unknown_valid_amount_count=sum(aggregate.valid_amount_count for aggregate in canonical_aggregates.values()),
            unknown_rejected_amount_count=sum(
                aggregate.rejected_amount_count for aggregate in canonical_aggregates.values()
            ),
            junk_occupation_counts=dict(self.junk_occupations),
            missing_junk_occupation_count=self.missing_junk_occupation_count,
            selected_nonempty_occupation_count=sum(self.selected_occupations.values()),
            selected_blank_occupation_count=self.selected_blank_occupation_count,
            selected_junk_equivalent_occupation_count=self.selected_junk_equivalent_occupation_count,
            selected_occupation_counts=dict(self.selected_occupations),
            occupation_ceiling_candidate_counts=dict(self.occupation_ceiling_candidates),
            selected_sample_digest=self.selected_sample_hasher.hexdigest(),
        )


def accumulate_coverage_metrics(rows: Iterable[EmployerRow], selection_rule: SelectionRule) -> CoverageMetrics:
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


def _build_canonical_aggregates(
    aggregate_builders: Mapping[str, _EmployerAggregateBuilder],
) -> dict[str, EmployerAggregate]:
    return {canonical_employer: builder.to_aggregate() for canonical_employer, builder in aggregate_builders.items()}


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


def _update_selected_sample_digest(sample_hasher: _SampleHasher, source_row_index: int, row: EmployerRow) -> None:
    sample_hasher.update(f"row_index={source_row_index}\n".encode())
    for field_name, raw_value in sorted(row.items()):
        if "=" in field_name or "\x00" in field_name or "\r" in field_name or "\n" in field_name:
            raise ValueError("sample digest field names must not contain delimiters")
        value = "" if raw_value is None else raw_value
        sample_hasher.update(f"{field_name}=".encode())
        if "\x00" in value or "\r" in value or "\n" in value:
            encoded_value = value.encode()
            sample_hasher.update(b"\x00")
            sample_hasher.update(len(encoded_value).to_bytes(8, byteorder="big"))
            sample_hasher.update(encoded_value)
        else:
            # Preserve the established baseline digest for ordinary source rows.
            sample_hasher.update(value.encode())
        sample_hasher.update(b"\n")
    sample_hasher.update(b"\n")


def _occupation_is_junk_equivalent(occupation: str) -> bool:
    canonical_occupation = canonicalize_employer(occupation)
    if canonical_occupation in NON_INDUSTRY_SIGNAL_OCCUPATIONS:
        return True
    return is_junk_employer(occupation)


def rank_top_unmapped_employers(
    employer_aggregates: Mapping[str, EmployerAggregate], *, limit: int
) -> tuple[EmployerAggregate, ...]:
    """Rank canonical employers by descending selected rows and lexical tie-break."""
    _validate_top_unmapped_limit(limit)
    ranked_aggregates = sorted(
        employer_aggregates.values(),
        key=lambda item: (-item.selected_row_count, item.canonical_employer),
    )
    return tuple(ranked_aggregates[:limit])


def measure_reference_overlap(
    employer_aggregates: Mapping[str, EmployerAggregate],
    reference_records: Iterable[ReferenceEmployerRecord],
) -> ReferenceOverlapMetrics:
    """Count classified reference names that join to selected unknown employers."""
    classified_reference_employers = {
        canonical_employer
        for record in reference_records
        if record.classification_code and record.classification_code.strip()
        if (canonical_employer := canonicalize_employer(record.organization_name)) is not None
    }
    matched_employers = tuple(sorted(classified_reference_employers.intersection(employer_aggregates)))
    return ReferenceOverlapMetrics(
        matched_selected_row_count=sum(
            employer_aggregates[canonical_employer].selected_row_count for canonical_employer in matched_employers
        ),
        matched_distinct_canonical_employer_count=len(matched_employers),
        matched_canonical_employers=matched_employers,
    )


def rank_top_occupations(occupation_counts: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    """Rank occupation strings by descending selected rows and lexical tie-break."""
    return tuple(sorted(occupation_counts.items(), key=lambda item: (-item[1], item[0])))


def choose_observed_curve_limit(ranked_occupations: tuple[tuple[str, int], ...]) -> int:
    """Choose the top-N cutoff at the largest observed frequency drop."""
    if not ranked_occupations:
        return 0

    largest_drop = 0
    cutoff = len(ranked_occupations)
    for index, (_, count) in enumerate(ranked_occupations[:-1]):
        next_count = ranked_occupations[index + 1][1]
        drop = count - next_count
        if drop > largest_drop:
            largest_drop = drop
            cutoff = index + 1
    return cutoff


def coverage_ceiling_summary(metrics: CoverageMetrics) -> CoverageCeilingSummary:
    """Calculate the Stage 1 ceiling frame alongside current combined reach."""
    ranked_occupations = rank_top_occupations(metrics.occupation_ceiling_candidate_counts)
    occupation_top_limit = choose_observed_curve_limit(ranked_occupations)
    occupation_ceiling_count = sum(count for _, count in ranked_occupations[:occupation_top_limit])
    external_reference_ceiling_count = sum(metrics.unmapped_canonical_employer_counts.values())
    combined_ceiling_count = metrics.known_industry_count + external_reference_ceiling_count
    return CoverageCeilingSummary(
        selected_row_count=metrics.selected_row_count,
        known_industry_count=metrics.known_industry_count,
        occupation_top_limit=occupation_top_limit,
        occupation_ceiling_count=occupation_ceiling_count,
        external_reference_ceiling_count=external_reference_ceiling_count,
        combined_ceiling_count=combined_ceiling_count,
        required_bar_count=REQUIRED_DERIVED_COVERAGE_BAR,
        clears_required_bar=combined_ceiling_count > REQUIRED_DERIVED_COVERAGE_BAR,
    )


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
    try:
        return f"{value.quantize(Decimal('0.01'))}"
    except InvalidOperation:
        return f"{value:.2E}"


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
    stage_1_ceiling_lines = _render_stage_1_ceiling_analysis(metrics, neutralize_untrusted_text)
    external_reference_disposition_lines = _render_external_reference_disposition(neutralize_untrusted_text)
    pool_distribution = _pool_distribution(ranked_top_100, metrics.unknown_non_junk_count)
    lines = [
        "# Employer industry coverage random baseline",
        "",
        _render_coverage_verdict(metrics),
        "",
        *_render_receipt_header(metadata, selection_rule, neutralize_untrusted_text),
        *_render_metric_summary(metrics),
        "All three shares use the selected-row sample as their denominator. The unknown numerator excludes junk rows.",
        "",
        "## Landed occupation rules",
        "",
        *_render_landed_occupation_rules(metrics),
        "",
        "## Stage 1 reachable ceilings",
        "",
        *stage_1_ceiling_lines,
        "",
        "## Stage 3 external-reference disposition",
        "",
        *external_reference_disposition_lines,
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
            "|": "&#124;",
            "\r": " ",
            "\n": " ",
            "\u2028": " ",
            "\u2029": " ",
        }
    )
    return lambda value: str(value).translate(markdown_neutralization)


def _render_external_reference_disposition(
    neutralize_untrusted_text: Callable[[object], str],
) -> list[str]:
    sample_identity = STAGE_3_FIXED_SAMPLE_IDENTITY
    candidate_lines = [
        (
            f"{neutralize_untrusted_text(candidate.source_name)}: "
            f"{sample_identity.known_or_derived_count:,} known-or-derived + "
            f"{candidate.matched_row_count:,} {neutralize_untrusted_text(candidate.match_frame)} = "
            f"{candidate.combined_row_count:,}; required > {REQUIRED_DERIVED_COVERAGE_BAR:,}; "
            f"short_by={candidate.shortfall_row_count:,}"
        )
        for candidate in STAGE_3_REJECTED_REFERENCE_CANDIDATES
    ]
    return [
        f"PRIOR_FIXED_SAMPLE_ARCHIVE_CYCLE: {sample_identity.archive_cycle}",
        "PRIOR_FIXED_SAMPLE_SELECTION_RULE: "
        f"seed={sample_identity.selection_seed}; "
        f"modulus={sample_identity.selection_modulus}; "
        f"target_bucket={sample_identity.target_bucket}",
        "PRIOR_FIXED_SAMPLE_SELECTED_SAMPLE_DIGEST: "
        f"{neutralize_untrusted_text(sample_identity.selected_sample_digest)}",
        f"PRIOR_FIXED_SAMPLE_KNOWN_OR_DERIVED_COUNT: {sample_identity.known_or_derived_count:,}",
        "PRIOR_FIXED_SAMPLE_EXTERNAL_REFERENCE_DISPOSITION: "
        f"{neutralize_untrusted_text(STAGE_3_EXTERNAL_REFERENCE_DISPOSITION)}",
        *candidate_lines,
    ]


def _render_receipt_header(
    metadata: ReceiptMetadata, selection_rule: SelectionRule, neutralize_untrusted_text: Callable[[object], str]
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
        _render_share("Known-or-derived industry share", metrics.known_industry_count, metrics.selected_row_count),
        _render_share("Unknown non-junk share", metrics.unknown_non_junk_count, metrics.selected_row_count),
        (
            "Stage 1 employer-only baseline: "
            f"junk={metrics.employer_only_junk_count:,}; "
            f"known={metrics.employer_only_known_industry_count:,}; "
            f"unknown_non_junk={metrics.employer_only_unknown_non_junk_count:,}"
        ),
        f"Occupation-derived industry rows: **{metrics.occupation_derived_industry_count:,}**",
        _render_known_or_derived_bar_result(metrics),
        _render_raised_floor_arithmetic(metrics),
        "",
    ]


def _render_coverage_verdict(metrics: CoverageMetrics) -> str:
    if metrics.known_industry_count > REQUIRED_DERIVED_COVERAGE_BAR:
        verdict = "BAR_CLEARED"
    elif metrics.occupation_derived_industry_count > 0:
        verdict = "IMPROVED_BELOW_BAR"
    else:
        verdict = "CEILING_CONFIRMED"
    return f"## EMPLOYER COVERAGE VERDICT: {verdict}"


def _render_landed_occupation_rules(metrics: CoverageMetrics) -> list[str]:
    lines = []
    for occupation, industry in OCCUPATION_INDUSTRIES.items():
        measured_count = metrics.occupation_derived_rule_counts.get(occupation, 0)
        lines.append(
            f"- {occupation} -> {industry}; measured derived rows: {measured_count:,}; "
            f"hand-calculated specimen: RETIRED + {occupation} -> {industry}"
        )
    lines.append(
        "PRECEDENCE_RULE: employer-derived industry wins; occupation is used only when employer evidence is unknown."
    )
    return lines


def _render_known_or_derived_bar_result(metrics: CoverageMetrics) -> str:
    clears_bar = metrics.known_industry_count > REQUIRED_DERIVED_COVERAGE_BAR
    return (
        "KNOWN_OR_DERIVED_BAR_RESULT: "
        f"{metrics.known_industry_count:,} / {metrics.selected_row_count:,}; "
        f"required > {REQUIRED_DERIVED_COVERAGE_BAR:,}; clears={clears_bar}"
    )


def _render_raised_floor_arithmetic(metrics: CoverageMetrics) -> str:
    floor_count = math.ceil(INDUSTRY_BY_EMPLOYER_MIN_COVERAGE * metrics.selected_row_count - 1e-12)
    headroom_rows = metrics.known_industry_count - floor_count
    floor_satisfied = metrics.known_industry_count / metrics.selected_row_count >= INDUSTRY_BY_EMPLOYER_MIN_COVERAGE
    return (
        "RAISED_FLOOR_ARITHMETIC: "
        f"measured={metrics.known_industry_count:,} / {metrics.selected_row_count:,}; "
        f"floor={floor_count:,} / {metrics.selected_row_count:,}; "
        f"headroom_rows={headroom_rows:,}; floor_satisfied={floor_satisfied}"
    )


def _render_signed_net_denominator(metrics: CoverageMetrics) -> str:
    return (
        "UNKNOWN_POOL_SIGNED_NET_DENOMINATOR: "
        f"{_render_decimal(metrics.unknown_signed_net_amount)} "
        f"(valid_amount_rows={metrics.unknown_valid_amount_count:,}; "
        f"rejected_amount_rows={metrics.unknown_rejected_amount_count:,})"
    )


def _render_top_employer_table(
    top_unmapped: tuple[EmployerAggregate, ...], neutralize_untrusted_text: Callable[[object], str]
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


def _render_raw_variants(variant_counts: Mapping[str, int], neutralize_untrusted_text: Callable[[object], str]) -> str:
    ranked_variants = sorted(variant_counts.items(), key=lambda item: (-item[1], item[0]))
    return "; ".join(f"{neutralize_untrusted_text(raw_employer)}: {count:,}" for raw_employer, count in ranked_variants)


def _render_cumulative_frames(ranked_top_100: tuple[EmployerAggregate, ...], metrics: CoverageMetrics) -> list[str]:
    cumulative_lines = []
    for top_limit in CUMULATIVE_TOP_LIMITS:
        selected_aggregates = ranked_top_100[:top_limit]
        row_numerator = sum(item.selected_row_count for item in selected_aggregates)
        amount_numerator = sum((item.signed_net_amount for item in selected_aggregates), Decimal("0"))
        cumulative_lines.append(_render_cumulative_frame(top_limit, row_numerator, amount_numerator, metrics))
    return cumulative_lines


def _render_cumulative_frame(
    top_limit: int, row_numerator: int, amount_numerator: Decimal, metrics: CoverageMetrics
) -> str:
    row_share = _render_percentage(row_numerator, metrics.unknown_non_junk_count)
    amount_share = _render_percentage(amount_numerator, metrics.unknown_signed_net_amount)
    return (
        f"CUMULATIVE_SHARE_TOP_{top_limit}: rows={row_numerator:,} / "
        f"{metrics.unknown_non_junk_count:,}; row_share={row_share}; "
        f"signed_net={_render_decimal(amount_numerator)} / "
        f"{_render_decimal(metrics.unknown_signed_net_amount)}; signed_net_share={amount_share}"
    )


def _pool_distribution(ranked_top_100: tuple[EmployerAggregate, ...], unknown_non_junk_count: int) -> str:
    if unknown_non_junk_count == 0:
        return "LONG_TAILED"
    top_100_count = sum(item.selected_row_count for item in ranked_top_100[:100])
    if top_100_count * 2 >= unknown_non_junk_count:
        return "HEAD_HEAVY"
    return "LONG_TAILED"


def _render_stage_1_ceiling_analysis(
    metrics: CoverageMetrics, neutralize_untrusted_text: Callable[[object], str]
) -> list[str]:
    summary = coverage_ceiling_summary(metrics)
    full_top_limit = choose_observed_curve_limit(rank_top_occupations(metrics.selected_occupation_counts))
    full_occupation_lines = _render_top_occupation_lines(
        metrics.selected_occupation_counts, full_top_limit, neutralize_untrusted_text
    )
    ceiling_occupation_lines = _render_top_occupation_lines(
        metrics.occupation_ceiling_candidate_counts,
        summary.occupation_top_limit,
        neutralize_untrusted_text,
    )
    return [
        _render_occupation_partition(metrics),
        f"FULL_SELECTED_OCCUPATION_TOP_N_CHOSEN_BY_CURVE: {full_top_limit:,}\n"
        "Top occupation strings by frequency across all selected rows:",
        *full_occupation_lines,
        f"OCCUPATION_CEILING_TOP_N_CHOSEN_BY_CURVE: {summary.occupation_top_limit:,}\n"
        "Top eligible occupation strings in the junk-employer ceiling frame:",
        *ceiling_occupation_lines,
        _render_ceiling_line("OCCUPATION_DERIVED_CEILING", summary.occupation_ceiling_count, metrics),
        _render_ceiling_line("EXTERNAL_REFERENCE_CEILING", summary.external_reference_ceiling_count, metrics),
        _render_combined_ceiling_line(summary, metrics),
        *_render_anti_stop_decision_menu(summary),
    ]


def _render_occupation_partition(metrics: CoverageMetrics) -> str:
    industry_signal_non_empty_count = (
        metrics.selected_nonempty_occupation_count - metrics.selected_junk_equivalent_occupation_count
    )
    return (
        "Occupation partition: "
        f"industry_signal_non_empty={industry_signal_non_empty_count:,}; "
        f"junk_equivalent_non_empty={metrics.selected_junk_equivalent_occupation_count:,}; "
        f"blank={metrics.selected_blank_occupation_count:,}; "
        f"selected_rows={metrics.selected_row_count:,}"
    )


def _render_top_occupation_lines(
    occupation_counts: Mapping[str, int], top_limit: int, neutralize_untrusted_text: Callable[[object], str]
) -> list[str]:
    ranked_occupations = rank_top_occupations(occupation_counts)
    selected_occupations = ranked_occupations[:top_limit]
    if not selected_occupations:
        return ["No occupation strings were selected in this frame."]
    return [f"- {neutralize_untrusted_text(occupation)}: {count:,}" for occupation, count in selected_occupations]


def _render_ceiling_line(label: str, numerator: int, metrics: CoverageMetrics) -> str:
    return (
        f"{label}: {numerator:,} / {metrics.selected_row_count:,} = "
        f"{_render_percentage(numerator, metrics.selected_row_count)}"
    )


def _render_combined_ceiling_line(summary: CoverageCeilingSummary, metrics: CoverageMetrics) -> str:
    return (
        "COMBINED_CEILING_ARITHMETIC: "
        f"{summary.known_industry_count:,} known-or-derived + "
        f"{summary.external_reference_ceiling_count:,} external = {summary.combined_ceiling_count:,} / "
        f"{metrics.selected_row_count:,} = "
        f"{_render_percentage(summary.combined_ceiling_count, metrics.selected_row_count)}; "
        f"required > {summary.required_bar_count:,}"
    )


def _render_anti_stop_decision_menu(summary: CoverageCeilingSummary) -> list[str]:
    if summary.clears_required_bar:
        return ["ANTI_STOP_DECISION_MENU: not required; combined ceiling clears the bar."]
    return [
        "ANTI_STOP_DECISION_MENU:",
        "- gap_spec: name the smallest source-linked rule or reference-data unblocker.",
        "- proxy_offer: state any approximate path and its bias/tolerance limits.",
        "- conditional_disposition: name what ships, reverts, or parks.",
    ]


def assert_stage_1_baseline(archive_cycle: int, selection_rule: SelectionRule, metrics: CoverageMetrics) -> None:
    """Fail when the canonical archive selection or employer partition drifts."""
    actual = {
        "archive_cycle": archive_cycle,
        "selection_seed": selection_rule.seed,
        "selection_modulus": selection_rule.modulus,
        "target_bucket": selection_rule.target_bucket,
        **{field: getattr(metrics, field) for field in STAGE_1_BASELINE if hasattr(metrics, field)},
        "junk_count": metrics.employer_only_junk_count,
        "known_industry_count": metrics.employer_only_known_industry_count,
        "unknown_non_junk_count": metrics.employer_only_unknown_non_junk_count,
    }
    drift = [
        f"{field} expected {_format_baseline_value(expected)}, measured {_format_baseline_value(actual[field])}"
        for field, expected in STAGE_1_BASELINE.items()
        if actual[field] != expected
    ]
    if drift:
        raise RuntimeError(f"Stage 1 baseline drift: {'; '.join(drift)}")


def _format_baseline_value(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


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
    parser.add_argument("--assert-stage-1-baseline", action="store_true")
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
    if arguments.assert_stage_1_baseline:
        assert_stage_1_baseline(arguments.cycle, selection_rule, metrics)
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
