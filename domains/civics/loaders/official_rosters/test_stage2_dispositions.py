"""Contract tests for the Stage 2 NC roster disposition artifact.

The disposition JSON (docs/live-state/2026_08_02_nc_roster_spine_dispositions.json)
is the test-backed verdict for all 43 existing NC roster refresh jobs. These tests
lock the artifact to the live refresh-job key set and to an honest working/repaired
contract so a stale or fabricated entry cannot pass silently.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from core.refresh.job_builders import build_refresh_plan

pytestmark = pytest.mark.dev_repo_only(
    private_asset="docs/live-state/2026_08_02_nc_roster_spine_dispositions.json",
    owner="NC roster disposition contract",
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DISPOSITIONS_PATH = _REPO_ROOT / "docs" / "live-state" / "2026_08_02_nc_roster_spine_dispositions.json"

# Stage 1 receipt timestamp; every disposition must have been probed after it.
_STAGE1_RECEIPT_TIMESTAMP = datetime.fromisoformat("2026-08-02T05:21:36+00:00")

_JOB_KEY_PREFIXES = ("civics-roster-", "civic-rosters-")
_WORKING_DISPOSITIONS = {"working", "repaired"}
_ALLOWED_DISPOSITIONS = _WORKING_DISPOSITIONS | {
    "blocked",
    "invalid_roster_shape",
    "js_render_shell",
    "no_individuated_roster",
}
_REQUIRED_FIELDS = ("source_id", "source_url", "body_key", "disposition", "http_status", "rows_parsed", "probed_at")
# Stage 2 requires every dropped/deferred source to explain itself, not just name a reason.
_REQUIRED_NON_WORKING_EVIDENCE_FIELDS = (
    "reason",
    "conditional_decision",
    "gap_spec",
    "smallest_unblock",
    "proxy_or_tolerance",
)
_MIN_NON_NULL_HTTP_STATUS = 40


def _expected_job_keys() -> set[str]:
    plan = build_refresh_plan(scope="all", job_key_prefixes=_JOB_KEY_PREFIXES)
    return {job.key for job in plan}


def _load_dispositions() -> dict[str, dict[str, object]]:
    return json.loads(_DISPOSITIONS_PATH.read_text(encoding="utf-8"))


def _assert_working_entries_valid(dispositions: dict[str, dict[str, object]]) -> None:
    """Fail if any working/repaired entry lacks a live 200 fetch with parsed rows.

    This is the load-bearing guard: it must be able to go red, which the mutation
    tests below prove by flipping a real working entry to http_status=202 / rows=0.
    """
    for job_key, entry in dispositions.items():
        if entry["disposition"] in _WORKING_DISPOSITIONS:
            assert entry["http_status"] == 200, f"{job_key}: working entry must record http_status 200"
            assert isinstance(entry["rows_parsed"], int) and entry["rows_parsed"] > 0, (
                f"{job_key}: working entry must record rows_parsed > 0"
            )


def test_disposition_keys_equal_the_live_43_refresh_job_keys() -> None:
    dispositions = _load_dispositions()
    assert set(dispositions) == _expected_job_keys()
    assert len(dispositions) == 43


def test_every_entry_declares_required_fields_and_allowed_disposition() -> None:
    dispositions = _load_dispositions()
    for job_key, entry in dispositions.items():
        for field_name in _REQUIRED_FIELDS:
            assert field_name in entry, f"{job_key}: missing required field {field_name}"
        assert entry["disposition"] in _ALLOWED_DISPOSITIONS, (
            f"{job_key}: unexpected disposition {entry['disposition']}"
        )


def test_working_and_repaired_entries_record_live_200_with_parsed_rows() -> None:
    _assert_working_entries_valid(_load_dispositions())


def test_at_least_40_entries_have_non_null_http_status() -> None:
    dispositions = _load_dispositions()
    non_null = [entry for entry in dispositions.values() if entry["http_status"] is not None]
    assert len(non_null) >= _MIN_NON_NULL_HTTP_STATUS


def test_every_probe_timestamp_is_after_the_stage1_receipt() -> None:
    dispositions = _load_dispositions()
    for job_key, entry in dispositions.items():
        probed_at = datetime.fromisoformat(str(entry["probed_at"]).replace("Z", "+00:00"))
        assert probed_at > _STAGE1_RECEIPT_TIMESTAMP, f"{job_key}: probed_at must be after the Stage 1 receipt"


def _assert_non_working_entries_valid(dispositions: dict[str, dict[str, object]]) -> None:
    """Fail if any dropped/deferred entry omits the Stage 2-required evidence fields.

    Stage 2 makes reason, conditional decision, gap spec, smallest unblock, and
    proxy/tolerance mandatory for every non-working source, so an incomplete
    disposition cannot drive the lane verdict. The mutation tests below prove this
    guard goes red when any one of those fields is dropped.
    """
    for job_key, entry in dispositions.items():
        if entry["disposition"] in _WORKING_DISPOSITIONS:
            continue
        for field_name in _REQUIRED_NON_WORKING_EVIDENCE_FIELDS:
            assert str(entry.get(field_name, "")).strip() != "", (
                f"{job_key}: non-working entry must record a non-empty {field_name}"
            )


def test_non_working_entries_record_reason_and_disposition_evidence() -> None:
    _assert_non_working_entries_valid(_load_dispositions())


def test_legislative_duplicate_district_sources_are_not_classified_as_working() -> None:
    dispositions = _load_dispositions()
    expected_duplicate_districts = {
        "civic-rosters-nc-senate": (53, "18, 23, 34"),
        "civics-roster-nc_general_assembly_house_roster": (125, "40, 47, 60, 90, 119"),
    }

    for job_key, (row_count, duplicate_districts) in expected_duplicate_districts.items():
        entry = dispositions[job_key]
        assert entry["disposition"] == "invalid_roster_shape"
        assert entry["http_status"] == 200
        assert entry["rows_parsed"] == row_count
        assert duplicate_districts in str(entry["reason"])


def _first_non_working_key(dispositions: dict[str, dict[str, object]]) -> str:
    return next(key for key, entry in dispositions.items() if entry["disposition"] not in _WORKING_DISPOSITIONS)


@pytest.mark.parametrize("field_name", _REQUIRED_NON_WORKING_EVIDENCE_FIELDS)
def test_guard_goes_red_when_a_non_working_entry_drops_required_evidence(field_name: str) -> None:
    dispositions = _load_dispositions()
    mutated = copy.deepcopy(dispositions)
    del mutated[_first_non_working_key(mutated)][field_name]
    with pytest.raises(AssertionError):
        _assert_non_working_entries_valid(mutated)


@pytest.mark.parametrize("field_name", _REQUIRED_NON_WORKING_EVIDENCE_FIELDS)
def test_guard_goes_red_when_a_non_working_entry_blanks_required_evidence(field_name: str) -> None:
    dispositions = _load_dispositions()
    mutated = copy.deepcopy(dispositions)
    mutated[_first_non_working_key(mutated)][field_name] = "   "
    with pytest.raises(AssertionError):
        _assert_non_working_entries_valid(mutated)


def _first_working_key(dispositions: dict[str, dict[str, object]]) -> str:
    return next(key for key, entry in dispositions.items() if entry["disposition"] in _WORKING_DISPOSITIONS)


def test_guard_goes_red_when_a_working_entry_is_mutated_to_http_202() -> None:
    dispositions = _load_dispositions()
    mutated = copy.deepcopy(dispositions)
    mutated[_first_working_key(mutated)]["http_status"] = 202
    with pytest.raises(AssertionError):
        _assert_working_entries_valid(mutated)


def test_guard_goes_red_when_a_working_entry_is_mutated_to_zero_rows() -> None:
    dispositions = _load_dispositions()
    mutated = copy.deepcopy(dispositions)
    mutated[_first_working_key(mutated)]["rows_parsed"] = 0
    with pytest.raises(AssertionError):
        _assert_working_entries_valid(mutated)
