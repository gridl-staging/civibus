"""Tests for the deterministic FEC employer-industry coverage measurement."""

from __future__ import annotations

from collections.abc import Iterator
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


def test_top_unmapped_ranking_uses_count_then_raw_string() -> None:
    ranked = rank_top_unmapped_employers(
        {
            "Zebra Lab": 2,
            "Alpha Lab": 2,
            "Small Town Workshop": 3,
            "Beta Lab": 1,
        },
        limit=3,
    )

    assert [(item.raw_employer, item.count) for item in ranked] == [
        ("Small Town Workshop", 3),
        ("Alpha Lab", 2),
        ("Zebra Lab", 2),
    ]


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
    assert "Execution locality: `test-host &#91;forged&#93;(https://example.invalid)`" in receipt
    assert "Archive cycle: `2024`" in receipt
    assert "Archive path: `/canonical/data/&#96;forged&#96;/itcont24.zip`" in receipt
    assert "SHA-256 of `1:{source_row_index}` modulo `1` equals target bucket `0`" in receipt
    assert "Selected rows (sample size): **5**" in receipt
    assert "Scanned rows: **5**" in receipt
    assert "Junk employer share: **20.000000%** (1 / 5)" in receipt
    assert "Known-industry share: **20.000000%** (1 / 5)" in receipt
    assert "Unknown non-junk share: **60.000000%** (3 / 5)" in receipt
    assert "1. Small Town Workshop: 2" in receipt
    assert "2. &lt;script&gt;alert(1)&lt;/script&gt; ## Forged receipt section: 1" in receipt
    assert "<script>" not in receipt
    assert "\n## Forged receipt section" not in receipt
    assert "[forged](https://example.invalid)" not in receipt
    assert "No third-party service participated" in receipt


def test_argument_parser_exposes_reproducible_defaults_and_output_override(tmp_path: Path) -> None:
    output_path = tmp_path / "receipt.md"

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
