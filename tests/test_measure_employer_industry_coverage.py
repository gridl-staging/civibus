"""Tests for the deterministic FEC employer-industry coverage measurement."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.measure_employer_industry_coverage as coverage_script
from domains.campaign_finance.normalize.employers import INDUSTRY_BY_EMPLOYER_MIN_COVERAGE
from scripts.measure_employer_industry_coverage import (
    ReferenceEmployerRecord,
    ReceiptMetadata,
    SelectionRule,
    _CoverageAccumulator,
    accumulate_coverage_metrics,
    build_argument_parser,
    choose_observed_curve_limit,
    coverage_ceiling_summary,
    iter_selected_rows,
    measure_reference_overlap,
    rank_top_occupations,
    rank_top_unmapped_employers,
    render_markdown_receipt,
    source_row_is_selected,
)


def _employer_rows(*employers: str | None) -> Iterator[dict[str, str | None]]:
    for employer in employers:
        yield {"EMPLOYER": employer}


def _row(
    employer: str | None,
    amount: str | None = None,
    occupation: str | None = None,
) -> dict[str, str | None]:
    return {
        "EMPLOYER": employer,
        "TRANSACTION_AMT": amount,
        "OCCUPATION": occupation,
    }


def _ceiling_rows() -> list[dict[str, str | None]]:
    return [
        _row("Google LLC", "100.00", "ENGINEER"),
        _row("RETIRED", "7.00", "RETIRED"),
        _row("NONE", "bad", ""),
        _row("N/A", None, None),
        _row("Acme, Inc", "10.25", "OWNER"),
        _row("Acme LLC", "-3.25", "ENGINEER"),
        _row("Beta Lab", "", "PHYSICIAN"),
        _row("SELF EMPLOYED", "11.00", "PHYSICIAN"),
        _row("UNEMPLOYED", "12.00", "ATTORNEY"),
    ]


def test_source_row_selection_is_stable_and_changes_with_rule_inputs() -> None:
    baseline = SelectionRule(seed=20260727, modulus=7, target_bucket=2)
    same_rule = SelectionRule(seed=20260727, modulus=7, target_bucket=2)
    different_seed = SelectionRule(seed=20260728, modulus=7, target_bucket=2)
    different_bucket = SelectionRule(seed=20260727, modulus=7, target_bucket=3)

    baseline_indices = [index for index in range(40) if source_row_is_selected(index, baseline)]

    assert baseline_indices == [4, 14, 24, 27, 35, 38]
    assert baseline_indices == [index for index in range(40) if source_row_is_selected(index, same_rule)]
    assert baseline_indices != [index for index in range(40) if source_row_is_selected(index, different_seed)]
    assert baseline_indices != [index for index in range(40) if source_row_is_selected(index, different_bucket)]


def test_fixed_sample_rule_pins_source_indexes_and_employer_partition() -> None:
    rule = SelectionRule(seed=20260727, modulus=4096, target_bucket=0)
    selected_employers = {
        192: "Google LLC",
        7986: "RETIRED",
        13331: "Acme LLC",
        14389: "NONE",
    }

    selected_indices = [index for index in range(14390) if source_row_is_selected(index, rule)]
    rows = ({"EMPLOYER": selected_employers.get(index, "unselected noise")} for index in range(14390))
    metrics = accumulate_coverage_metrics(rows, rule)

    assert selected_indices == [192, 7986, 13331, 14389]
    assert metrics.scanned_row_count == 14390
    assert metrics.selected_row_count == 4
    assert metrics.junk_count == 2
    assert metrics.known_industry_count == 1
    assert metrics.unknown_non_junk_count == 1


def test_baseline_gate_pins_selected_sample_identity_when_aggregate_counts_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = SelectionRule(seed=20260727, modulus=4096, target_bucket=0)
    baseline_rows = ({"EMPLOYER": "unselected noise", "TRANSACTION_AMT": None, "OCCUPATION": None} for _ in range(193))
    moved_rows = (
        {"EMPLOYER": "different unselected noise", "TRANSACTION_AMT": None, "OCCUPATION": None} for _ in range(193)
    )
    baseline_metrics = accumulate_coverage_metrics(baseline_rows, rule)
    moved_metrics = accumulate_coverage_metrics(moved_rows, rule)
    assert baseline_metrics.selected_sample_digest == (
        "3dfce43d4e48d1a8454955c2410720d90511d080cec0475e8068ffb410b213ab"
    )
    monkeypatch.setattr(
        coverage_script,
        "STAGE_1_BASELINE",
        {
            "archive_cycle": 2024,
            "selection_seed": rule.seed,
            "selection_modulus": rule.modulus,
            "target_bucket": rule.target_bucket,
            "scanned_row_count": baseline_metrics.scanned_row_count,
            "selected_row_count": baseline_metrics.selected_row_count,
            "junk_count": baseline_metrics.junk_count,
            "known_industry_count": baseline_metrics.known_industry_count,
            "unknown_non_junk_count": baseline_metrics.unknown_non_junk_count,
            "selected_sample_digest": baseline_metrics.selected_sample_digest,
        },
    )

    with pytest.raises(RuntimeError, match="selected_sample_digest expected"):
        coverage_script.assert_stage_1_baseline(2024, rule, moved_metrics)

    select_all = SelectionRule(seed=1, modulus=1, target_bucket=0)
    injected_field_metrics = accumulate_coverage_metrics(
        [{"EMPLOYER": "Acme\nOCCUPATION=ATTORNEY"}],
        select_all,
    )
    separate_fields_metrics = accumulate_coverage_metrics(
        [{"EMPLOYER": "Acme", "OCCUPATION": "ATTORNEY"}],
        select_all,
    )

    assert injected_field_metrics.selected_sample_digest != separate_fields_metrics.selected_sample_digest


def test_selection_uses_source_row_index_and_remains_lazy() -> None:
    rows_yielded = 0

    def repeated_employers() -> Iterator[dict[str, str | None]]:
        nonlocal rows_yielded
        for _ in range(100):
            rows_yielded += 1
            yield {"EMPLOYER": "SAME EMPLOYER"}

    rule = SelectionRule(seed=20260727, modulus=7, target_bucket=2)
    selected_rows = iter_selected_rows(repeated_employers(), rule)

    assert rows_yielded == 0
    first_index, first_row = next(selected_rows)
    assert first_index == 4
    assert first_row == {"EMPLOYER": "SAME EMPLOYER"}
    assert rows_yielded == 5


def test_metrics_use_public_normalizers_and_hand_calculated_counts() -> None:
    metrics = accumulate_coverage_metrics(
        _employer_rows(
            "Google LLC",
            "RETIRED",
            "Small Town Workshop",
            "Small Town Workshop",
            "Acme, Inc",
            "Acme LLC",
            "Zebra Lab",
            "Alpha Lab",
        ),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    assert metrics.scanned_row_count == 8
    assert metrics.selected_row_count == 8
    assert metrics.distinct_raw_employer_count == 7
    assert metrics.distinct_canonical_employer_count == 5
    assert metrics.junk_count == 1
    assert metrics.known_industry_count == 1
    assert metrics.unknown_non_junk_count == 6
    assert metrics.unmapped_raw_employer_counts == {
        "Small Town Workshop": 2,
        "Acme, Inc": 1,
        "Acme LLC": 1,
        "Zebra Lab": 1,
        "Alpha Lab": 1,
    }


def test_metrics_count_occupation_derived_rows_in_known_industry_numerator() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Google LLC", occupation="ATTORNEY"),
            _row("RETIRED", occupation="ATTORNEY"),
            _row("SELF EMPLOYED", occupation="PHYSICIAN"),
            _row("Acme LLC", occupation="TEACHER"),
            _row("Beta Lab", occupation="CONSULTANT"),
            _row("NONE", occupation="RETIRED"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    assert metrics.selected_row_count == 6
    assert metrics.known_industry_count == 4
    assert metrics.junk_count == 1
    assert metrics.unknown_non_junk_count == 1
    assert metrics.employer_only_known_industry_count == 1
    assert metrics.occupation_derived_industry_count == 3
    assert metrics.occupation_derived_rule_counts == {
        "ATTORNEY": 1,
        "PHYSICIAN": 1,
        "TEACHER": 1,
    }
    assert metrics.known_industry_count == metrics.employer_only_known_industry_count + 3
    assert metrics.junk_count + metrics.known_industry_count + metrics.unknown_non_junk_count == 6


def test_metrics_accumulate_canonical_unknown_amounts_and_junk_occupations() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Google LLC", "100.00", "ENGINEER"),
            _row("RETIRED", "7.00", "RETIRED"),
            _row("NONE", "bad", ""),
            _row("N/A", None, None),
            _row("Acme, Inc", "10.25", "OWNER"),
            _row("Acme LLC", "-3.25", ""),
            _row("Acme", "malformed", None),
            _row("Beta Lab", "", "SCIENTIST"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    assert metrics.scanned_row_count == 8
    assert metrics.selected_row_count == 8
    assert metrics.junk_count == 3
    assert metrics.known_industry_count == 1
    assert metrics.unknown_non_junk_count == 4
    assert metrics.unknown_valid_amount_count == 2
    assert metrics.unknown_rejected_amount_count == 2
    assert metrics.unknown_signed_net_amount == Decimal("7.00")
    assert metrics.junk_occupation_counts == {"RETIRED": 1}
    assert metrics.missing_junk_occupation_count == 2

    assert metrics.unmapped_canonical_employer_counts == {"ACME": 3, "BETA LAB": 1}
    assert metrics.unmapped_canonical_employer_aggregates["ACME"].selected_row_count == 3
    assert metrics.unmapped_canonical_employer_aggregates["ACME"].signed_net_amount == Decimal("7.00")
    assert metrics.unmapped_canonical_employer_aggregates["ACME"].valid_amount_count == 2
    assert metrics.unmapped_canonical_employer_aggregates["ACME"].rejected_amount_count == 1
    assert metrics.unmapped_canonical_employer_aggregates["ACME"].raw_variant_counts == {
        "Acme, Inc": 1,
        "Acme LLC": 1,
        "Acme": 1,
    }


def test_accumulator_add_selected_row_uses_occupation_fallback_without_changing_sample_identity() -> None:
    accumulator = _CoverageAccumulator()
    accumulator.scanned_row_count = 1
    row = _row("RETIRED", "10.00", "ATTORNEY")

    accumulator._add_selected_row(row)
    metrics = accumulator.to_metrics()

    assert metrics.selected_row_count == 1
    assert metrics.known_industry_count == 1
    assert metrics.occupation_derived_industry_count == 1
    assert metrics.junk_count == 0
    assert metrics.unknown_non_junk_count == 0
    assert metrics.employer_only_junk_count == 1
    assert metrics.employer_only_known_industry_count == 0
    assert metrics.employer_only_unknown_non_junk_count == 0


def test_accumulator_tracks_full_occupation_partition_and_ceiling_counts() -> None:
    accumulator = _CoverageAccumulator()
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)

    for index, row in enumerate(_ceiling_rows()):
        accumulator.add_source_row(index, row, rule)
    metrics = accumulator.to_metrics()

    assert metrics.selected_row_count == 9
    assert metrics.selected_nonempty_occupation_count == 7
    assert metrics.selected_blank_occupation_count == 2
    assert metrics.selected_junk_equivalent_occupation_count == 2
    assert metrics.selected_occupation_counts == {
        "ENGINEER": 2,
        "PHYSICIAN": 2,
        "ATTORNEY": 1,
        "OWNER": 1,
        "RETIRED": 1,
    }
    assert metrics.occupation_ceiling_candidate_counts == {
        "ATTORNEY": 1,
        "PHYSICIAN": 1,
    }
    assert rank_top_occupations(metrics.occupation_ceiling_candidate_counts) == (
        ("ATTORNEY", 1),
        ("PHYSICIAN", 1),
    )


def test_receipt_ranks_full_selected_occupations_separately_from_ceiling_candidates() -> None:
    metrics = accumulate_coverage_metrics(
        _ceiling_rows(),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    receipt = render_markdown_receipt(
        ReceiptMetadata(
            archive_cycle=2024,
            archive_path=Path("/tmp/itcont24.zip"),
            execution_locality="test",
        ),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        metrics,
        top_limit=10,
    )

    assert "FULL_SELECTED_OCCUPATION_TOP_N_CHOSEN_BY_CURVE: 2" in receipt
    assert "Top occupation strings by frequency across all selected rows:" in receipt
    assert "- ENGINEER: 2" in receipt
    assert "- PHYSICIAN: 2" in receipt
    assert "OCCUPATION_CEILING_TOP_N_CHOSEN_BY_CURVE: 2" in receipt
    assert "Top eligible occupation strings in the junk-employer ceiling frame:" in receipt
    assert "- ATTORNEY: 1" in receipt
    assert receipt.count("- ENGINEER: 2") == 1


def test_ambiguous_occupations_are_excluded_before_curve_cutoff() -> None:
    metrics = accumulate_coverage_metrics(
        [
            *[_row("RETIRED", occupation="ATTORNEY") for _ in range(5)],
            *[_row("RETIRED", occupation="PHYSICIAN") for _ in range(4)],
            *[_row("RETIRED", occupation="CONSULTANT") for _ in range(4)],
            *[_row("RETIRED", occupation="MANAGER") for _ in range(3)],
            _row("RETIRED", occupation="OWNER"),
            _row("RETIRED", occupation="TEACHER"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    assert metrics.occupation_ceiling_candidate_counts == {
        "ATTORNEY": 5,
        "PHYSICIAN": 4,
        "TEACHER": 1,
    }
    summary = coverage_ceiling_summary(metrics)
    assert summary.occupation_top_limit == 2
    assert summary.occupation_ceiling_count == 9
    assert summary.combined_ceiling_count == 10


def test_occupation_ceiling_canonicalizes_variants_before_curve_cutoff() -> None:
    rows = (
        [_row("RETIRED", occupation="Physician")] * 8
        + [_row("RETIRED", occupation="Attorney")] * 4
        + [_row("RETIRED", occupation="attorney.")] * 3
        + [_row("RETIRED", occupation="Teacher")] * 3
        + [_row("RETIRED", occupation="ATTORNEY!")] * 2
    )

    metrics = accumulate_coverage_metrics(
        rows,
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )
    summary = coverage_ceiling_summary(metrics)

    assert metrics.selected_occupation_counts == {
        "ATTORNEY!": 2,
        "Attorney": 4,
        "Physician": 8,
        "Teacher": 3,
        "attorney.": 3,
    }
    assert metrics.occupation_ceiling_candidate_counts == {
        "ATTORNEY": 9,
        "PHYSICIAN": 8,
        "TEACHER": 3,
    }
    assert summary.occupation_top_limit == 2
    assert summary.occupation_ceiling_count == 17


def test_stage_1_fixed_sample_ceiling_pins_corrected_partition_and_arithmetic() -> None:
    junk_rows = (
        [_row("RETIRED", occupation="ATTORNEY")] * 41
        + [_row("RETIRED", occupation="PHYSICIAN")] * 37
        + [_row("RETIRED", occupation="CONSULTANT")] * 37
        + [_row("RETIRED", occupation="TEACHER")] * 3
        + [_row("RETIRED", occupation="RETIRED")] * 9_862
    )
    rows = (
        junk_rows + [_row("Google LLC", occupation="ENGINEER")] * 370 + [_row("Acme LLC", occupation="ANALYST")] * 3_974
    )

    metrics = accumulate_coverage_metrics(
        rows,
        SelectionRule(seed=20260727, modulus=1, target_bucket=0),
    )
    summary = coverage_ceiling_summary(metrics)

    assert metrics.selected_row_count == 14_324
    assert (metrics.junk_count, metrics.known_industry_count, metrics.unknown_non_junk_count) == (
        9_899,
        451,
        3_974,
    )
    assert (
        metrics.employer_only_junk_count,
        metrics.employer_only_known_industry_count,
        metrics.employer_only_unknown_non_junk_count,
    ) == (
        9_980,
        370,
        3_974,
    )
    assert metrics.occupation_derived_industry_count == 81
    assert summary.occupation_top_limit == 2
    assert summary.occupation_ceiling_count == 78
    assert summary.external_reference_ceiling_count == 3_974
    assert summary.combined_ceiling_count == 4_425


def test_observed_curve_limit_uses_largest_frequency_drop_with_tie_boundary() -> None:
    ranked_occupations = (
        ("ENGINEER", 9),
        ("ATTORNEY", 8),
        ("PHYSICIAN", 8),
        ("TEACHER", 3),
        ("LAWYER", 3),
        ("NURSE", 2),
    )

    assert choose_observed_curve_limit(ranked_occupations) == 3
    assert choose_observed_curve_limit((("ENGINEER", 2), ("ATTORNEY", 2))) == 2
    assert choose_observed_curve_limit(()) == 0


def test_coverage_ceiling_summary_keeps_achieved_and_ceiling_populations_distinct() -> None:
    metrics = accumulate_coverage_metrics(
        _ceiling_rows(),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    summary = coverage_ceiling_summary(metrics)

    assert summary.known_industry_count == 4
    assert summary.occupation_top_limit == 2
    assert summary.occupation_ceiling_count == 2
    assert summary.occupation_ceiling_count == sum(
        count
        for _, count in rank_top_occupations(metrics.occupation_ceiling_candidate_counts)[
            : summary.occupation_top_limit
        ]
    )
    assert summary.external_reference_ceiling_count == 2
    assert summary.combined_ceiling_count == 6
    assert summary.required_bar_count == 1104
    assert summary.clears_required_bar is False


def test_metrics_reject_non_finite_amounts_from_signed_net_totals() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Acme, Inc", "10.00"),
            _row("Acme LLC", "-3.00"),
            _row("Acme", "NaN"),
            _row("Acme", "sNaN"),
            _row("Acme", "Infinity"),
            _row("Acme", "-Infinity"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    assert metrics.unknown_non_junk_count == 6
    assert metrics.unknown_valid_amount_count == 2
    assert metrics.unknown_rejected_amount_count == 4
    assert metrics.unknown_signed_net_amount == Decimal("7.00")

    aggregate = metrics.unmapped_canonical_employer_aggregates["ACME"]
    assert aggregate.selected_row_count == 6
    assert aggregate.valid_amount_count == 2
    assert aggregate.rejected_amount_count == 4
    assert aggregate.signed_net_amount == Decimal("7.00")

    extreme_finite_metrics = accumulate_coverage_metrics(
        [_row("Extreme Lab", "1e999999")],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )
    extreme_finite_receipt = render_markdown_receipt(
        ReceiptMetadata(
            archive_cycle=2024,
            archive_path=Path("/tmp/itcont24.zip"),
            execution_locality="test",
        ),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        extreme_finite_metrics,
        top_limit=1,
    )

    assert extreme_finite_metrics.unknown_valid_amount_count == 1
    assert "UNKNOWN_POOL_SIGNED_NET_DENOMINATOR: 1.00E+999999" in extreme_finite_receipt


def test_top_unmapped_ranking_uses_count_then_raw_string() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Zebra Lab", "1"),
            _row("Zebra Lab", "2"),
            _row("Alpha Lab", "3"),
            _row("Alpha Lab", "4"),
            _row("Small Town Workshop", "5"),
            _row("Small Town Workshop", "6"),
            _row("Small Town Workshop", "7"),
            _row("Beta Lab", "8"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    ranked = rank_top_unmapped_employers(
        metrics.unmapped_canonical_employer_aggregates,
        limit=3,
    )

    assert [(item.canonical_employer, item.selected_row_count) for item in ranked] == [
        ("SMALL TOWN WORKSHOP", 3),
        ("ALPHA LAB", 2),
        ("ZEBRA LAB", 2),
    ]


def test_reference_overlap_uses_canonical_keys_and_counts_selected_rows() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Acme, Inc"),
            _row("Acme LLC"),
            _row("Acme"),
            _row("Beta Lab"),
            _row("Unmatched Workshop"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )
    reference_records = [
        ReferenceEmployerRecord(organization_name="ACME CORP.", classification_code="3571"),
        ReferenceEmployerRecord(organization_name="Acme Inc", classification_code="3571"),
        ReferenceEmployerRecord(organization_name="Beta Lab LLC", classification_code="E20"),
        ReferenceEmployerRecord(organization_name="Unmatched Workshop", classification_code=" "),
        ReferenceEmployerRecord(organization_name=None, classification_code="9999"),
    ]

    overlap = measure_reference_overlap(
        metrics.unmapped_canonical_employer_aggregates,
        reference_records,
    )

    assert overlap.matched_selected_row_count == 4
    assert overlap.matched_distinct_canonical_employer_count == 2
    assert overlap.matched_canonical_employers == ("ACME", "BETA LAB")


def test_receipt_renders_canonical_cumulative_frames_and_distribution_rule() -> None:
    heavy_rows = [_row(f"Employer {index:03d} LLC", "1.00") for index in range(100)]
    heavy_rows.extend(_row(f"Tail {index:03d}", "-0.50") for index in range(100))
    metrics = accumulate_coverage_metrics(heavy_rows, SelectionRule(seed=1, modulus=1, target_bucket=0))

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        metrics,
        top_limit=100,
    )

    assert receipt.count("CUMULATIVE_SHARE_TOP_") == 4
    assert "CUMULATIVE_SHARE_TOP_10: rows=10 / 200; row_share=5.000000%" in receipt
    assert "CUMULATIVE_SHARE_TOP_25: rows=25 / 200; row_share=12.500000%" in receipt
    assert "CUMULATIVE_SHARE_TOP_50: rows=50 / 200; row_share=25.000000%" in receipt
    assert "CUMULATIVE_SHARE_TOP_100: rows=100 / 200; row_share=50.000000%" in receipt
    assert "signed_net=100.00 / 50.00; signed_net_share=200.000000%" in receipt
    assert "UNKNOWN_POOL_SIGNED_NET_DENOMINATOR: 50.00 (valid_amount_rows=200; rejected_amount_rows=0)" in receipt
    assert "POOL_DISTRIBUTION: HEAD_HEAVY" in receipt
    assert (
        sum(1 for line in receipt.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()) == 100
    )
    assert "| 1 | EMPLOYER 000 | 1 | 1 | 0 | 1.00 | Employer 000 LLC: 1 |" in receipt


def test_receipt_renders_not_computable_signed_net_share_when_denominator_is_zero() -> None:
    metrics = accumulate_coverage_metrics(
        [
            _row("Balanced One LLC", "5.00"),
            _row("Balanced One Inc", "-5.00"),
            _row("Balanced Two LLC", "2.00"),
            _row("Balanced Two Inc", "-2.00"),
            _row("Tail Lab", "malformed"),
        ],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        metrics,
        top_limit=100,
    )

    assert "UNKNOWN_POOL_SIGNED_NET_DENOMINATOR: 0.00 (valid_amount_rows=4; rejected_amount_rows=1)" in receipt
    assert "signed_net=0.00 / 0.00; signed_net_share=NOT_COMPUTABLE" in receipt
    assert "POOL_DISTRIBUTION: HEAD_HEAVY" in receipt


def test_pool_distribution_is_long_tailed_below_boundary() -> None:
    rows = [_row(f"Head {index:03d}", "1.00") for index in range(100)]
    rows.extend(_row(f"Tail {index:03d}", "1.00") for index in range(101))
    metrics = accumulate_coverage_metrics(rows, SelectionRule(seed=1, modulus=1, target_bucket=0))

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        metrics,
        top_limit=100,
    )

    assert "CUMULATIVE_SHARE_TOP_100: rows=100 / 201; row_share=49.751244%" in receipt
    assert "POOL_DISTRIBUTION: LONG_TAILED" in receipt


def test_receipt_honors_positive_top_limit_above_cumulative_frame_limit() -> None:
    rows = [_row(f"Employer {index:03d} LLC", "1.00") for index in range(125)]
    metrics = accumulate_coverage_metrics(rows, SelectionRule(seed=1, modulus=1, target_bucket=0))

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        SelectionRule(seed=1, modulus=1, target_bucket=0),
        metrics,
        top_limit=125,
    )

    table_row_count = sum(
        1 for line in receipt.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    )
    assert table_row_count == 125
    assert "## Top 125 unmapped non-junk employers" in receipt
    assert "| 125 | EMPLOYER 124 | 1 | 1 | 0 | 1.00 | Employer 124 LLC: 1 |" in receipt
    assert "CUMULATIVE_SHARE_TOP_100: rows=100 / 125; row_share=80.000000%" in receipt


@pytest.mark.parametrize("top_limit", [0, -1])
def test_receipt_rejects_non_positive_top_limit(top_limit: int) -> None:
    metrics = accumulate_coverage_metrics(
        [_row("Acme LLC", "1.00")],
        SelectionRule(seed=1, modulus=1, target_bucket=0),
    )

    with pytest.raises(ValueError, match="top-unmapped limit must be greater than zero"):
        render_markdown_receipt(
            ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
            SelectionRule(seed=1, modulus=1, target_bucket=0),
            metrics,
            top_limit=top_limit,
        )


def test_zero_selected_rows_fail_instead_of_producing_vacuous_metrics() -> None:
    rule = SelectionRule(seed=20260727, modulus=7, target_bucket=2)

    with pytest.raises(ValueError, match="selected zero rows"):
        accumulate_coverage_metrics(_employer_rows("only row"), rule)


def test_rendered_receipt_exposes_reproducibility_and_denominators() -> None:
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(
        _employer_rows(
            "Google LLC",
            "RETIRED",
            "Small Town Workshop",
            "Small Town Workshop",
            "<script>alert(1)</script>\n## Forged receipt section | forged table cell",
        ),
        rule,
    )
    metadata = ReceiptMetadata(
        archive_cycle=2024,
        archive_path=Path("/canonical/data/`forged`/itcont24.zip"),
        execution_locality="test-host\n[forged](https://example.invalid)",
    )

    receipt = render_markdown_receipt(metadata, rule, metrics, top_limit=10)

    assert "# Employer industry coverage random baseline" in receipt
    assert "Execution locality: `test-host &#91;forged&#93;&#40;https://example.invalid&#41;`" in receipt
    assert "Archive cycle: `2024`" in receipt
    assert "Archive path: `/canonical/data/&#96;forged&#96;/itcont24.zip`" in receipt
    assert "SHA-256 of `1:{source_row_index}` modulo `1` equals target bucket `0`" in receipt
    assert "Selected rows (sample size): **5**" in receipt
    assert "Scanned rows: **5**" in receipt
    assert "Junk employer share: **20.000000%** (1 / 5)" in receipt
    assert "Known-or-derived industry share: **20.000000%** (1 / 5)" in receipt
    assert "Unknown non-junk share: **60.000000%** (3 / 5)" in receipt
    assert "KNOWN_OR_DERIVED_BAR_RESULT: 1 / 5; required > 1,104; clears=False" in receipt
    assert "| 1 | SMALL TOWN WORKSHOP | 2 | 0 | 2 | 0.00 | Small Town Workshop: 2 |" in receipt
    assert (
        "| 2 | SCRIPT ALERT 1 SCRIPT FORGED RECEIPT SECTION FORGED TABLE CELL | 1 | 0 | 1 | 0.00 | "
        "&lt;script&gt;alert&#40;1&#41;&lt;/script&gt; ## Forged receipt section "
        "&#124; forged table cell: 1 |"
    ) in receipt
    assert "POOL_DISTRIBUTION: HEAD_HEAVY" in receipt
    assert (
        "Occupation partition: industry_signal_non_empty=0; junk_equivalent_non_empty=0; blank=5; selected_rows=5"
    ) in receipt
    assert "No occupation strings were selected in this frame." in receipt
    assert "<script>" not in receipt
    assert "\n## Forged receipt section" not in receipt
    assert "[forged](https://example.invalid)" not in receipt
    assert "No third-party service participated" in receipt


def test_receipt_renders_stage_1_ceiling_sections_and_anti_stop_menu() -> None:
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(_ceiling_rows(), rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )

    assert "## Stage 1 reachable ceilings" in receipt
    assert (
        "Occupation partition: industry_signal_non_empty=5; junk_equivalent_non_empty=2; blank=2; selected_rows=9"
    ) in receipt
    assert "FULL_SELECTED_OCCUPATION_TOP_N_CHOSEN_BY_CURVE: 2" in receipt
    assert "OCCUPATION_CEILING_TOP_N_CHOSEN_BY_CURVE: 2" in receipt
    assert "- ATTORNEY: 1" in receipt
    assert "- PHYSICIAN: 1" in receipt
    assert "OCCUPATION_DERIVED_CEILING: 2 / 9 = 22.222222%" in receipt
    assert "Occupation-derived industry rows: **3**" in receipt
    assert "EXTERNAL_REFERENCE_CEILING: 2 / 9 = 22.222222%" in receipt
    assert "KNOWN_OR_DERIVED_BAR_RESULT: 4 / 9; required > 1,104; clears=False" in receipt
    assert "COMBINED_CEILING_ARITHMETIC: 4 known-or-derived + 2 external = 6 / 9 = 66.666667%" in receipt
    assert "ANTI_STOP_DECISION_MENU:" in receipt
    assert "- gap_spec: name the smallest source-linked rule or reference-data unblocker." in receipt


def test_receipt_preserves_stage_3_no_source_disposition_and_rejection_arithmetic() -> None:
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(_ceiling_rows(), rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )

    assert "## Stage 3 external-reference disposition" in receipt
    assert "PRIOR_FIXED_SAMPLE_EXTERNAL_REFERENCE_DISPOSITION: NO SOURCE SELECTED" in receipt
    assert ("SEC/EDGAR: 837 known-or-derived + 197 matched = 1,034; required > 1,104; short_by=71") in receipt
    assert (
        "IRS EO BMF/NTEE: 837 known-or-derived + 188 generous upper bound = 1,025; required > 1,104; short_by=80"
    ) in receipt


def test_final_floor_arithmetic_uses_measured_metrics_and_owner_constant() -> None:
    rows = (
        [_row("Google LLC", occupation="ENGINEER")] * 370
        + [_row("RETIRED", occupation="ATTORNEY")] * 467
        + [_row("Acme LLC", occupation="ANALYST")] * 3_597
        + [_row("RETIRED", occupation="RETIRED")] * 9_890
    )
    rule = SelectionRule(seed=20260727, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(rows, rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )

    assert metrics.selected_row_count == 14_324
    assert metrics.known_industry_count == 837
    assert metrics.known_industry_count / metrics.selected_row_count == INDUSTRY_BY_EMPLOYER_MIN_COVERAGE
    assert (
        "RAISED_FLOOR_ARITHMETIC: measured=837 / 14,324; floor=837 / 14,324; headroom_rows=0; floor_satisfied=True"
    ) in receipt


@pytest.mark.parametrize(
    ("rows", "expected_verdict"),
    [
        ([_row("Google LLC")] * 1_105, "BAR_CLEARED"),
        (
            [_row("Google LLC")] * 370 + [_row("RETIRED", occupation="ATTORNEY")],
            "IMPROVED_BELOW_BAR",
        ),
        ([_row("Google LLC")] * 370, "CEILING_CONFIRMED"),
    ],
)
def test_receipt_emits_exactly_one_unfenced_terminal_verdict(
    rows: list[dict[str, str | None]],
    expected_verdict: str,
) -> None:
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(rows, rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )
    verdict_lines = [line for line in receipt.splitlines() if line.startswith("## EMPLOYER COVERAGE VERDICT:")]

    assert verdict_lines == [f"## EMPLOYER COVERAGE VERDICT: {expected_verdict}"]
    assert "```" not in verdict_lines[0]


def test_receipt_states_landed_rules_expectations_and_precedence() -> None:
    rule = SelectionRule(seed=1, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(_ceiling_rows(), rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2024, archive_path=Path("/tmp/itcont24.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )

    assert "## Landed occupation rules" in receipt
    assert (
        "- ATTORNEY -> Legal; measured derived rows: 1; hand-calculated specimen: RETIRED + ATTORNEY -> Legal"
        in receipt
    )
    assert (
        "- PHYSICIAN -> Health Care; measured derived rows: 2; "
        "hand-calculated specimen: RETIRED + PHYSICIAN -> Health Care"
    ) in receipt
    assert (
        "- TEACHER -> Education; measured derived rows: 0; hand-calculated specimen: RETIRED + TEACHER -> Education"
        in receipt
    )
    assert (
        "PRECEDENCE_RULE: employer-derived industry wins; occupation is used only when employer evidence is unknown."
    ) in receipt


def test_stage_3_disposition_is_labeled_as_prior_fixed_sample_for_noncanonical_receipts() -> None:
    rule = SelectionRule(seed=99, modulus=1, target_bucket=0)
    metrics = accumulate_coverage_metrics(_ceiling_rows(), rule)

    receipt = render_markdown_receipt(
        ReceiptMetadata(archive_cycle=2030, archive_path=Path("/tmp/itcont30.zip"), execution_locality="test"),
        rule,
        metrics,
        top_limit=10,
    )

    assert "Archive cycle: `2030`" in receipt
    assert "SHA-256 of `99:{source_row_index}` modulo `1` equals target bucket `0`" in receipt
    assert "PRIOR_FIXED_SAMPLE_EXTERNAL_REFERENCE_DISPOSITION: NO SOURCE SELECTED" in receipt
    assert "PRIOR_FIXED_SAMPLE_ARCHIVE_CYCLE: 2024" in receipt
    assert "PRIOR_FIXED_SAMPLE_SELECTION_RULE: seed=20260727; modulus=4096; target_bucket=0" in receipt
    assert (
        "PRIOR_FIXED_SAMPLE_SELECTED_SAMPLE_DIGEST: 6999f5676192c378abfc6baa2075de8594fbe8cf81818cfd2fa4529fd758c419"
    ) in receipt
    assert "PRIOR_FIXED_SAMPLE_KNOWN_OR_DERIVED_COUNT: 837" in receipt
    assert "EXTERNAL_REFERENCE_DISPOSITION: NO SOURCE SELECTED" not in receipt.splitlines()


def test_argument_parser_exposes_reproducible_defaults_and_output_override() -> None:
    output_path = Path("receipt.md")

    arguments = build_argument_parser().parse_args(["--output", str(output_path)])

    assert arguments.cycle == 2024
    assert arguments.seed == 20260727
    assert arguments.modulus == 4096
    assert arguments.target_bucket == 0
    assert arguments.top_limit == 20
    assert arguments.output == output_path


def test_archive_baseline_gate_fails_before_writing_a_drifted_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "itcont24.zip"
    archive_path.touch()
    output_path = tmp_path / "receipt.md"
    archive_rows = [_row("unselected noise")] * 192 + [_row("Google LLC")]
    monkeypatch.setattr(coverage_script, "resolve_fec_data_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_script, "fec_bulk_data_cache_path", lambda *_args, **_kwargs: archive_path)
    monkeypatch.setattr(coverage_script, "read_bulk_file", lambda *_args, **_kwargs: iter(archive_rows))

    with pytest.raises(RuntimeError) as error:
        coverage_script.main(
            [
                "--assert-stage-1-baseline",
                "--output",
                str(output_path),
            ]
        )

    assert str(error.value) == (
        "Stage 1 baseline drift: scanned_row_count expected 58,208,756, measured 193; "
        "selected_row_count expected 14,324, measured 1; junk_count expected 9,980, measured 0; "
        "known_industry_count expected 370, measured 1; unknown_non_junk_count expected 3,974, measured 0; "
        "selected_sample_digest expected 6999f5676192c378abfc6baa2075de8594fbe8cf81818cfd2fa4529fd758c419, "
        "measured 1246c995aadf520c5ef93751a787e02dd8ab37ec46bfdaa8e28bea2bd944e4dc"
    )
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("modulus", "target_bucket", "message"),
    [
        (0, 0, "modulus"),
        (7, -1, "target_bucket"),
        (7, 7, "target_bucket"),
    ],
)
def test_selection_rule_rejects_invalid_buckets(modulus: int, target_bucket: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SelectionRule(seed=1, modulus=modulus, target_bucket=target_bucket)
