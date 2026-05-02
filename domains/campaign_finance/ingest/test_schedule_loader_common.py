from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domains.campaign_finance.ingest import schedule_b_loader, schedule_e_loader, schedule_loader_common


def _helper_module_name(helper: object) -> str:
    function_object = getattr(helper, "__func__", helper)
    return function_object.__module__


def test_schedule_loaders_use_shared_common_helper_implementations() -> None:
    expected_module = schedule_loader_common.__name__
    shared_helpers = (
        "_validate_batch_size",
        "_require_text",
        "_require_decimal",
        "_optional_date",
        "_normalize_amendment_indicator",
        "_json_compatible_raw_fields",
    )

    for loader_module in (schedule_b_loader, schedule_e_loader):
        for helper_name in shared_helpers:
            helper = getattr(loader_module, helper_name)
            assert _helper_module_name(helper) == expected_module


def test_schedule_specific_validation_error_messages_still_include_loader_name() -> None:
    with pytest.raises(ValueError, match="committee_id is required for Schedule B ingest"):
        schedule_b_loader._require_text({}, "committee_id")

    with pytest.raises(ValueError, match="spe_id is required for Schedule E ingest"):
        schedule_e_loader._require_text({}, "spe_id")


def test_shared_json_raw_field_conversion_stays_stable_for_dates_and_decimals() -> None:
    row = {"amount": Decimal("12.34"), "transaction_date": date(2026, 4, 17), "note": "ok"}
    expected = {
        "amount": "12.34",
        "transaction_date": "2026-04-17",
        "note": "ok",
    }
    assert schedule_b_loader._json_compatible_raw_fields(row) == expected
    assert schedule_e_loader._json_compatible_raw_fields(row) == expected
