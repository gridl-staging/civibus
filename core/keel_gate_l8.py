"""Compatibility adapter for the L8 regression gate entrypoint.

The implementation owner lives in ``core.entity_resolution.l8_regression``.
This module remains as a stable import/module CLI boundary.
"""

from __future__ import annotations

from core.entity_resolution import l8_regression as _l8_regression

RegressionPairCase = _l8_regression.RegressionPairCase
RegressionPairsFixture = _l8_regression.RegressionPairsFixture
FalsePositiveCorpusCase = _l8_regression.FalsePositiveCorpusCase
FalsePositiveCorpusFixture = _l8_regression.FalsePositiveCorpusFixture

score_regression_pair_case = _l8_regression.score_regression_pair_case
score_false_positive_case = _l8_regression.score_false_positive_case
evaluate_regression_pairs = _l8_regression.evaluate_regression_pairs
run_l8_regression_gate = _l8_regression.run_l8_regression_gate
build_argument_parser = _l8_regression.build_argument_parser
main = _l8_regression.main

__all__ = [
    "RegressionPairCase",
    "RegressionPairsFixture",
    "FalsePositiveCorpusCase",
    "FalsePositiveCorpusFixture",
    "score_regression_pair_case",
    "score_false_positive_case",
    "evaluate_regression_pairs",
    "run_l8_regression_gate",
    "build_argument_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
