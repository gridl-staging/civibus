"""Tests for the deterministic FEC employer-industry coverage measurement."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.measure_employer_industry_coverage import (
    ReceiptMetadata,
    SelectionRule,
    accumulate_coverage_metrics,
    build_argument_parser,
    iter_selected_rows,
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
            "<script>alert(1)</script>\n## Forged receipt section",
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
    assert "Known-industry share: **20.000000%** (1 / 5)" in receipt
    assert "Unknown non-junk share: **60.000000%** (3 / 5)" in receipt
    assert "| 1 | SMALL TOWN WORKSHOP | 2 | 0 | 2 | 0.00 | Small Town Workshop: 2 |" in receipt
    assert (
        "| 2 | SCRIPT ALERT 1 SCRIPT FORGED RECEIPT SECTION | 1 | 0 | 1 | 0.00 | "
        "&lt;script&gt;alert&#40;1&#41;&lt;/script&gt; ## Forged receipt section: 1 |"
    ) in receipt
    assert "POOL_DISTRIBUTION: HEAD_HEAVY" in receipt
    assert "No junk occupations were supplied." in receipt
    assert "<script>" not in receipt
    assert "\n## Forged receipt section" not in receipt
    assert "[forged](https://example.invalid)" not in receipt
    assert "No third-party service participated" in receipt


def test_argument_parser_exposes_reproducible_defaults_and_output_override() -> None:
    output_path = Path("receipt.md")

    arguments = build_argument_parser().parse_args(["--output", str(output_path)])

    assert arguments.cycle == 2024
    assert arguments.seed == 20260727
    assert arguments.modulus == 4096
    assert arguments.target_bucket == 0
    assert arguments.top_limit == 20
    assert arguments.output == output_path


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
