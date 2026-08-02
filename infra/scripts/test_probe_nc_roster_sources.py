"""Tests for the Stage 2 NC roster re-fetch probe.

Every case injects a stubbed fetch so the probe never touches the network. The stubs
prove the probe fails closed: an unfillable sample, a recorded non-200, a live non-2xx,
and a live zero-row re-parse must each drive a non-zero exit, and the deterministic
sample cannot be hand-picked.
"""

from __future__ import annotations

from pathlib import Path

from infra.scripts.probe_nc_roster_sources import (
    main,
    refetch_entry,
    run_probe,
    select_sample,
)

# Real-structure Senate contact XML: one NC Class II member (Tillis) => 1 parsed row.
_SENATE_XML_ONE_NC_CLASS_II = """<?xml version="1.0" encoding="UTF-8"?>
<contact_information>
  <member>
    <member_full>Tillis (R-NC)</member_full>
    <last_name>Tillis</last_name>
    <first_name>Thom</first_name>
    <state>NC</state>
    <class>Class II</class>
    <website>https://tillis.senate.gov</website>
    <bioguide_id>T000476</bioguide_id>
  </member>
</contact_information>
"""

_SENATE_XML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?>\n<contact_information></contact_information>\n'

_SENATE_URL = "https://www.senate.gov/general/contact_information/senators_cfm.xml"


def _senate_entry(*, http_status: int = 200, rows_parsed: int = 1, disposition: str = "working") -> dict[str, object]:
    return {
        "source_id": "us_senate_nc_class_ii",
        "source_url": _SENATE_URL,
        "body_key": "us_senate_nc_class_ii",
        "disposition": disposition,
        "http_status": http_status,
        "rows_parsed": rows_parsed,
        "probed_at": "2026-08-02T06:00:00Z",
    }


def _explode_fetch(url: str) -> tuple[int, str]:
    raise AssertionError(f"fetch must not be called for this entry (url={url})")


def test_select_sample_is_deterministic_sorted_prefix_regardless_of_insertion_order() -> None:
    dispositions = {
        "civic-rosters-z-last": _senate_entry(),
        "civic-rosters-a-first": _senate_entry(),
        "civic-rosters-m-mid": _senate_entry(),
        "civic-rosters-blocked": _senate_entry(disposition="blocked", http_status=403, rows_parsed=0),
    }
    assert select_sample(dispositions, 2) == ["civic-rosters-a-first", "civic-rosters-m-mid"]


def test_recorded_non_200_entry_fails_before_any_live_fetch() -> None:
    agreed, note = refetch_entry(_senate_entry(http_status=202), _explode_fetch)
    assert agreed is False
    assert "not 200" in note


def test_live_non_2xx_after_recorded_200_disagrees() -> None:
    agreed, note = refetch_entry(_senate_entry(), lambda url: (403, ""))
    assert agreed is False
    assert "403" in note

    agreed, note = refetch_entry(_senate_entry(), lambda url: (202, _SENATE_XML_ONE_NC_CLASS_II))
    assert agreed is False
    assert "202" in note

    def fail_fetch(url: str) -> tuple[int, str]:
        raise OSError(f"simulated transport failure for {url}")

    agreed, note = refetch_entry(_senate_entry(), fail_fetch)
    assert agreed is False
    assert "live fetch failed" in note

    agreed, note = refetch_entry(_senate_entry(), lambda url: (200, "not xml"))
    assert agreed is False
    assert "live parse failed" in note


def test_recorded_rows_but_live_zero_rows_disagrees() -> None:
    agreed, note = refetch_entry(_senate_entry(rows_parsed=1), lambda url: (200, _SENATE_XML_EMPTY))
    assert agreed is False
    assert "0 rows" in note


def test_recorded_count_drifting_to_a_different_positive_count_disagrees() -> None:
    """A stale recorded count must disagree even when the live re-parse still finds rows."""
    agreed, note = refetch_entry(_senate_entry(rows_parsed=5), lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II))
    assert agreed is False
    assert "5" in note and "1" in note


def test_recorded_zero_rows_but_live_rows_disagrees() -> None:
    agreed, note = refetch_entry(_senate_entry(rows_parsed=0), lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II))
    assert agreed is False


def test_matching_live_fetch_agrees() -> None:
    import socket

    import httpx
    import pytest

    from infra.scripts.probe_nc_roster_sources import default_fetch

    agreed, note = refetch_entry(_senate_entry(rows_parsed=1), lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II))
    assert agreed is True

    agreed, note = refetch_entry(_senate_entry(rows_parsed=1), lambda url: (206, _SENATE_XML_ONE_NC_CLASS_II))
    assert agreed is True

    requested_urls: list[str] = []
    request_kwargs: list[dict[str, object]] = []

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        requested_urls.append(url)
        request_kwargs.append(kwargs)
        return httpx.Response(
            302,
            headers={"location": "https://127.0.0.1/admin"},
            request=httpx.Request("GET", url),
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(httpx, "get", fake_get)
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))],
        )

        with pytest.raises(ValueError, match="public HTTPS"):
            default_fetch("http://example.com/roster")
        with pytest.raises(ValueError, match="public HTTPS"):
            default_fetch("https://localhost/roster")
        with pytest.raises(ValueError, match="public HTTPS"):
            default_fetch("https://224.0.0.1/roster")
        with pytest.raises(ValueError, match="public HTTPS"):
            default_fetch("https://example.com/roster")

    assert requested_urls == ["https://example.com/roster"]
    assert request_kwargs[0]["follow_redirects"] is False
    assert request_kwargs[0]["trust_env"] is False


def test_run_probe_counts_agreements_and_disagreements() -> None:
    dispositions = {
        "civic-rosters-good": _senate_entry(),
        "civic-rosters-bad-live": _senate_entry(),
    }
    dispositions["civic-rosters-good"]["source_url"] = f"{_SENATE_URL}?case=good"
    dispositions["civic-rosters-bad-live"]["source_url"] = f"{_SENATE_URL}?case=bad"

    def fetch(url: str) -> tuple[int, str]:
        if url.endswith("case=bad"):
            return (200, _SENATE_XML_EMPTY)
        return (200, _SENATE_XML_ONE_NC_CLASS_II)

    result = run_probe(dispositions, sample_size=2, fetch=fetch)
    assert result.sampled == 2
    assert result.agreed == 1
    assert result.disagreed == 1
    assert [(outcome.job_key, outcome.agreed) for outcome in result.outcomes] == [
        ("civic-rosters-bad-live", False),
        ("civic-rosters-good", True),
    ]


def _write(tmp_path: Path, dispositions: dict[str, dict[str, object]]) -> Path:
    import json

    path = tmp_path / "dispositions.json"
    path.write_text(json.dumps(dispositions), encoding="utf-8")
    return path


def test_main_exit_nonzero_when_sample_cannot_be_filled_so_sampled_zero_is_not_vacuous(tmp_path: Path) -> None:
    dispositions = {"civic-rosters-blocked": _senate_entry(disposition="blocked", http_status=403, rows_parsed=0)}
    path = _write(tmp_path, dispositions)
    exit_code = main(["--dispositions", str(path), "--sample", "8", "--min-working", "0"], fetch=_explode_fetch)
    assert exit_code == 1

    try:
        main(["--dispositions", str(path), "--sample", "0", "--min-working", "0"], fetch=_explode_fetch)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("--sample 0 must be rejected before it can produce a vacuous pass")


def test_main_exit_nonzero_when_working_floor_not_met(tmp_path: Path) -> None:
    dispositions = {"civic-rosters-good": _senate_entry()}
    path = _write(tmp_path, dispositions)
    exit_code = main(
        ["--dispositions", str(path), "--sample", "1", "--min-working", "15"],
        fetch=lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II),
    )
    assert exit_code == 1

    try:
        main(["--dispositions", str(path), "--sample", "1", "--min-working", "-1"], fetch=_explode_fetch)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("a negative working floor must be rejected instead of weakening the gate")


def test_main_exit_zero_when_sample_and_floor_satisfied(tmp_path: Path) -> None:
    dispositions = {f"civic-rosters-{i:02d}": _senate_entry() for i in range(20)}
    path = _write(tmp_path, dispositions)
    exit_code = main(
        ["--dispositions", str(path), "--sample", "8", "--min-working", "15"],
        fetch=lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II),
    )
    assert exit_code == 0


def test_main_exit_nonzero_when_a_sampled_entry_disagrees(tmp_path: Path) -> None:
    dispositions = {f"civic-rosters-{i:02d}": _senate_entry() for i in range(20)}
    path = _write(tmp_path, dispositions)

    def fetch(url: str) -> tuple[int, str]:
        return (200, _SENATE_XML_EMPTY)  # recorded rows>0 but live 0 => every sample disagrees

    exit_code = main(["--dispositions", str(path), "--sample", "8", "--min-working", "0"], fetch=fetch)
    assert exit_code == 1


def test_main_exit_nonzero_when_a_sampled_entry_row_count_drifts(tmp_path: Path) -> None:
    dispositions = {f"civic-rosters-{i:02d}": _senate_entry() for i in range(20)}
    dispositions["civic-rosters-00"]["rows_parsed"] = 7  # live re-parse still finds 1 row
    path = _write(tmp_path, dispositions)
    exit_code = main(
        ["--dispositions", str(path), "--sample", "8", "--min-working", "0"],
        fetch=lambda url: (200, _SENATE_XML_ONE_NC_CLASS_II),
    )
    assert exit_code == 1
