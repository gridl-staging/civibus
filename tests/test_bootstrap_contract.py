"""Compose-first-boot bootstrap contract canaries for Stage 1."""

from __future__ import annotations

import psycopg
import pytest

from test_support.bootstrap_canaries import _collect_missing_stage1_canaries


@pytest.mark.integration
def test_compose_only_bootstrap_provisions_stage1_canaries(db_conn: psycopg.Connection) -> None:
    # This contract must represent first-boot results only, with no runtime bootstrap helpers.
    missing_canaries = _collect_missing_stage1_canaries(db_conn)

    assert not missing_canaries, "Compose-first-boot contract is missing bootstrap canaries: " + ", ".join(
        missing_canaries
    )
