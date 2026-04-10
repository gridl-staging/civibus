from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import domains.campaign_finance.jurisdictions.states.NC.scraper.download as download_module
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    TransactionSearchCriteria,
    _EXPORT_BUTTON_SELECTOR,
    _NC_SEARCH_FORM_FIELDS,
    _SEARCH_BUTTON_SELECTOR,
    download_committee_document_export,
    download_transaction_export,
    download_transaction_export_playwright,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    parse_transactions,
)


def _is_playwright_timeout(error: Exception) -> bool:
    error_type = type(error)
    return error_type.__name__ == "TimeoutError" and error_type.__module__.startswith("playwright")


def _is_transient_network_failure(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "net::err_",
            "connection reset",
            "connection refused",
            "temporary failure in name resolution",
        )
    )


def _assert_integration_download_returns_nonempty_parseable_file(
    tmp_path: Path,
    *,
    criteria: TransactionSearchCriteria,
    parser: Callable[[Path], object],
) -> None:
    dest_path = tmp_path / "transinq_results.csv"
    try:
        download_transaction_export_playwright(criteria, dest_path)
    except RuntimeError as error:
        if "playwright" in str(error).lower():
            pytest.skip(f"Playwright unavailable for integration test: {error}")
        raise
    except Exception as error:  # noqa: BLE001
        if _is_playwright_timeout(error):
            pytest.skip(f"NC portal timed out during transaction integration test: {error}")
        if _is_transient_network_failure(error):
            pytest.skip(f"NC portal network failure during transaction integration test: {error}")
        raise

    assert dest_path.exists()
    assert dest_path.stat().st_size > 0
    assert list(parser(dest_path))


def _set_nc_playwright_available(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync_playwright: object,
) -> None:
    monkeypatch.setattr(download_module, "_sync_playwright", sync_playwright)
    monkeypatch.setattr(download_module, "_playwright_import_error", None)


def _build_mock_playwright_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    suggested_filename: str = "transinq_results.csv",
) -> dict[str, MagicMock]:
    playwright_manager = MagicMock()
    playwright_instance = MagicMock()
    browser = MagicMock()
    browser_context = MagicMock()
    page = MagicMock()
    search_button = MagicMock()
    export_button = MagicMock()
    download = MagicMock()
    download.suggested_filename = suggested_filename
    download.save_as.side_effect = lambda destination: Path(destination).write_text("downloaded csv", encoding="utf-8")
    download_info = MagicMock()
    download_info.value = download

    expect_download_cm = MagicMock()
    expect_download_cm.__enter__ = MagicMock(return_value=download_info)
    expect_download_cm.__exit__ = MagicMock(return_value=None)
    page.expect_download.return_value = expect_download_cm
    page.locator.side_effect = lambda selector: {
        "#btnSearch": search_button,
        "#btnExportResults": export_button,
    }.get(selector, MagicMock())

    playwright_manager.__enter__ = MagicMock(return_value=playwright_instance)
    playwright_manager.__exit__ = MagicMock(return_value=None)
    playwright_instance.chromium.launch.return_value = browser
    browser.new_context.return_value = browser_context
    browser_context.new_page.return_value = page

    _set_nc_playwright_available(
        monkeypatch,
        sync_playwright=MagicMock(return_value=playwright_manager),
    )

    return {
        "playwright_instance": playwright_instance,
        "browser": browser,
        "browser_context": browser_context,
        "page": page,
        "search_button": search_button,
        "export_button": export_button,
        "download": download,
    }


@pytest.mark.integration
def test_download_transaction_export_playwright_integration_returns_nonempty_parseable_file(
    tmp_path: Path,
) -> None:
    _assert_integration_download_returns_nonempty_parseable_file(
        tmp_path,
        criteria=TransactionSearchCriteria(
            last_name="ADAMS",
            date_from="01/01/2026",
            date_to="03/14/2026",
        ),
        parser=parse_transactions,
    )


class TestPlaywrightMissing:
    def test_playwright_missing_raises_runtime_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(download_module, "_sync_playwright", None)
        monkeypatch.setattr(
            download_module,
            "_playwright_import_error",
            ImportError("No module named 'playwright'"),
        )

        criteria = TransactionSearchCriteria(last_name="TEST")
        with pytest.raises(RuntimeError, match="Install download dependencies"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    def test_module_remains_importable_without_playwright(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(download_module, "_sync_playwright", None)
        monkeypatch.setattr(
            download_module,
            "_playwright_import_error",
            ImportError("No module named 'playwright'"),
        )
        assert callable(download_committee_document_export)
        assert callable(download_transaction_export)


class TestPlaywrightLifecycle:
    def test_creates_dest_parent_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        dest = tmp_path / "subdir" / "deep" / "out.csv"
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, dest)
        assert dest.parent.exists()

    def test_launches_chromium_headless_with_downloads(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["playwright_instance"].chromium.launch.assert_called_once_with(
            channel="chrome",
            headless=True,
        )
        mocks["browser"].new_context.assert_called_once_with(accept_downloads=True)

    def test_closes_context_and_browser_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["browser_context"].close.assert_called_once()
        mocks["browser"].close.assert_called_once()

    def test_closes_browser_when_context_creation_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        mocks["browser"].new_context.side_effect = RuntimeError("context setup failed")

        criteria = TransactionSearchCriteria(last_name="ADAMS")
        with pytest.raises(RuntimeError, match="context setup failed"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["browser"].close.assert_called_once()

    def test_closes_context_and_browser_when_page_interaction_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        mocks["page"].goto.side_effect = RuntimeError("navigation failed")

        criteria = TransactionSearchCriteria(last_name="ADAMS")
        with pytest.raises(RuntimeError, match="navigation failed"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["browser_context"].close.assert_called_once()
        mocks["browser"].close.assert_called_once()


class TestPlaywrightFlow:
    def test_navigates_to_search_url_and_fills_form(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(
            last_name="ADAMS",
            date_from="01/01/2026",
            date_to="03/14/2026",
        )
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["page"].goto.assert_called_once()
        goto_url = mocks["page"].goto.call_args[0][0]
        assert "/CFTxnLkup/" in goto_url

        fill_calls = {fill_call.args[0]: fill_call.args[1] for fill_call in mocks["page"].fill.call_args_list}
        assert fill_calls["#LastName"] == "ADAMS"
        assert fill_calls["#DateFrom"] == "01/01/2026"
        assert fill_calls["#DateTo"] == "03/14/2026"

    def test_form_fill_uses_live_option_values_for_select_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(
            last_name="ADAMS",
            trans_type="rec",
            county="92",
        )
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        select_calls = {
            select_call.args[0]: select_call.args[1] for select_call in mocks["page"].select_option.call_args_list
        }
        assert select_calls["#TransType"] == "rec"
        assert select_calls["#County"] == "92"

    def test_form_fill_checks_is_org_checkbox_before_org_name_fill(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(org_name="CIVIBUS PAC", is_org=True)
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        assert call.check("#IsOrg") in mocks["page"].mock_calls
        assert call.fill("#OrgName", "CIVIBUS PAC") in mocks["page"].mock_calls
        assert mocks["page"].mock_calls.index(call.check("#IsOrg")) < mocks["page"].mock_calls.index(
            call.fill("#OrgName", "CIVIBUS PAC")
        )

    def test_form_fill_uses_visible_committee_text_and_hidden_committee_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(
            committee_name="ADAMS COMMITTEE",
            committee_id="C123",
        )
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        evaluate_args = [evaluate_call.args for evaluate_call in mocks["page"].evaluate.call_args_list]
        assert any(args[1] == ["#CommID", "C123"] for args in evaluate_args)
        fill_calls = {fill_call.args[0]: fill_call.args[1] for fill_call in mocks["page"].fill.call_args_list}
        assert fill_calls["#CommText"] == "ADAMS COMMITTEE"
        assert "#CommID" not in fill_calls

    def test_classify_results_grid_failure_reports_502_and_error_state(self) -> None:
        message = download_module._classify_results_grid_failure(
            body_text="0 - 0 of 0 records Prev1Next Loading Results... error",
            grid_status_codes=(502,),
        )

        assert message is not None
        assert "GetPagedResults returned 502" in message
        assert "Loading Results... error" in message

    def test_form_fill_initializes_use_city_hidden_field_and_honors_true_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(city_letter="C", city="CARY", use_city=True)
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        evaluate_args = [evaluate_call.args for evaluate_call in mocks["page"].evaluate.call_args_list]
        assert any(args[1] == ["#UseCity", "false"] for args in evaluate_args)
        assert any(args[1] == ["#UseCity", "true"] for args in evaluate_args)

    def test_form_fill_waits_for_city_options_before_selecting_city(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        monkeypatch.setattr(
            download_module,
            "_NC_SEARCH_FORM_FIELDS",
            (
                ("city", "#City", "select"),
                ("county", "#County", "select"),
                ("city_letter", "#CityLetter", "select"),
            ),
        )
        criteria = TransactionSearchCriteria(county="92", city="CARY")
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        page_calls = mocks["page"].mock_calls
        county_call = call.select_option("#County", "92")
        mocks["page"].wait_for_function.assert_called_once()
        wait_kwargs = mocks["page"].wait_for_function.call_args.kwargs
        assert wait_kwargs["arg"] == ["#City", "CARY", "#County", "92"]
        assert wait_kwargs["timeout"] == 120_000
        assert (
            page_calls.index(county_call)
            < page_calls.index(
                call.wait_for_function(
                    mocks["page"].wait_for_function.call_args.args[0],
                    arg=["#City", "CARY", "#County", "92"],
                    timeout=120_000,
                )
            )
            < page_calls.index(call.select_option("#City", "CARY"))
        )

    def test_form_fill_applies_city_letter_before_city_even_when_mapping_order_differs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        monkeypatch.setattr(
            download_module,
            "_NC_SEARCH_FORM_FIELDS",
            (
                ("city", "#City", "select"),
                ("county", "#County", "select"),
                ("city_letter", "#CityLetter", "select"),
            ),
        )
        criteria = TransactionSearchCriteria(
            city_letter="C",
            city="CARY",
        )
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        page_calls = mocks["page"].mock_calls
        city_letter_call = call.select_option("#CityLetter", "C")
        wait_call = call.wait_for_function(
            mocks["page"].wait_for_function.call_args.args[0],
            arg=["#City", "CARY", "#CityLetter", "C"],
            timeout=120_000,
        )
        city_call = call.select_option("#City", "CARY")
        assert page_calls.index(city_letter_call) < page_calls.index(wait_call)
        assert page_calls.index(wait_call) < page_calls.index(city_call)

    def test_form_fill_checks_is_org_checkbox_when_true(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS", is_org=True)
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")
        mocks["page"].check.assert_called_once_with("#IsOrg")

    def test_form_fill_does_not_check_is_org_when_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS", is_org=False)
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")
        mocks["page"].check.assert_not_called()

    def test_form_fill_skips_empty_criteria_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        fill_selectors = [fill_call.args[0] for fill_call in mocks["page"].fill.call_args_list]
        assert "#LastName" in fill_selectors
        assert "#AmountFrom" not in fill_selectors
        assert "#FirstName" not in fill_selectors

    def test_clicks_search_button_after_form_fill(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, tmp_path / "out.csv")
        mocks["search_button"].click.assert_called_once()

    def test_waits_for_export_button_then_downloads_csv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        dest = tmp_path / "out.csv"
        criteria = TransactionSearchCriteria(last_name="ADAMS")
        download_transaction_export_playwright(criteria, dest)

        mocks["export_button"].wait_for.assert_called_once_with(
            state="visible",
            timeout=120_000,
        )
        mocks["page"].expect_download.assert_called_once_with(timeout=180_000)
        mocks["export_button"].click.assert_called_once_with(no_wait_after=True)
        saved_path = Path(mocks["download"].save_as.call_args.args[0])
        assert saved_path.name == dest.name
        assert saved_path.parent.parent == dest.parent
        assert saved_path.parent.name.startswith(f".{dest.name}.")

    def test_search_form_fields_mapping_covers_all_expected_criteria(self) -> None:
        mapped_attrs = {attr for attr, _, _ in _NC_SEARCH_FORM_FIELDS}
        expected_str_attrs = {
            "trans_type",
            "last_name",
            "first_name",
            "org_name",
            "committee_name",
            "committee_id",
            "date_from",
            "date_to",
            "amount_from",
            "amount_to",
            "county",
            "city",
            "city_letter",
        }
        assert mapped_attrs == expected_str_attrs

    def test_city_requires_county_or_city_letter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(city="CARY")

        with pytest.raises(ValueError, match="city requires a specific county or city_letter"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    @pytest.mark.parametrize("city_letter", ["All", "*"])
    def test_city_rejects_non_specific_city_letter_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        city_letter: str,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(county="0", city_letter=city_letter, city="CARY")

        with pytest.raises(ValueError, match="city requires a specific county or city_letter"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    def test_county_rejects_combined_specific_city_letter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(county="92", city_letter="C")

        with pytest.raises(
            ValueError,
            match="county cannot be combined with a specific city_letter",
        ):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    def test_org_name_requires_is_org_true(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(org_name="CIVIBUS PAC")

        with pytest.raises(ValueError, match="org_name requires is_org=True"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    def test_county_requires_portal_option_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(county="WAKE")

        with pytest.raises(ValueError, match="county must use the NC portal option value"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

    def test_trans_type_requires_known_portal_option_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _build_mock_playwright_stack(monkeypatch)
        criteria = TransactionSearchCriteria(trans_type="receipts")

        with pytest.raises(ValueError, match="trans_type must be one of the NC portal option values"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")


class TestPlaywrightFailurePaths:
    def test_export_button_timeout_raises_and_cleans_up(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        mocks["export_button"].wait_for.side_effect = TimeoutError(
            "Timeout 120000ms exceeded waiting for #btnExportResults"
        )

        criteria = TransactionSearchCriteria(last_name="ADAMS")
        with pytest.raises(TimeoutError, match="btnExportResults"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["browser_context"].close.assert_called_once()
        mocks["browser"].close.assert_called_once()

    def test_download_save_failure_raises_and_cleans_up(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        dest = tmp_path / "out.csv"
        legacy_part_path = dest.with_name("out.csv.part")
        sentinel = tmp_path / "sentinel.txt"
        sentinel.write_text("protected", encoding="utf-8")
        legacy_part_path.symlink_to(sentinel)

        def _write_partial_file_then_fail(part_destination: str) -> None:
            Path(part_destination).write_text("partial download", encoding="utf-8")
            raise RuntimeError("save failed")

        mocks["download"].save_as.side_effect = _write_partial_file_then_fail

        criteria = TransactionSearchCriteria(last_name="ADAMS")
        with pytest.raises(RuntimeError, match="save failed"):
            download_transaction_export_playwright(criteria, dest)

        mocks["browser_context"].close.assert_called_once()
        mocks["browser"].close.assert_called_once()
        assert not dest.exists()
        assert sentinel.read_text(encoding="utf-8") == "protected"
        assert not list(tmp_path.glob(".out.csv.*"))

    def test_search_button_click_failure_cleans_up(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        mocks = _build_mock_playwright_stack(monkeypatch)
        mocks["search_button"].click.side_effect = RuntimeError("click failed")

        criteria = TransactionSearchCriteria(last_name="ADAMS")
        with pytest.raises(RuntimeError, match="click failed"):
            download_transaction_export_playwright(criteria, tmp_path / "out.csv")

        mocks["browser_context"].close.assert_called_once()
        mocks["browser"].close.assert_called_once()


# -- 2026-cycle portal-contract lock tests --


class TestNCPlaywrightPortalContract2026:
    """Lock NC Playwright selectors for 2026 cycle.

    These are regression guards: if the NC SBE portal changes its DOM
    structure, these tests catch it before a live scrape attempt fails silently.
    """

    def test_search_button_selector_matches_portal_dom(self) -> None:
        assert _SEARCH_BUTTON_SELECTOR == "#btnSearch"

    def test_export_button_selector_matches_portal_dom(self) -> None:
        assert _EXPORT_BUTTON_SELECTOR == "#btnExportResults"

    def test_search_form_fields_include_date_selectors(self) -> None:
        field_map = {attr: selector for attr, selector, _ in _NC_SEARCH_FORM_FIELDS}
        assert field_map["date_from"] == "#DateFrom"
        assert field_map["date_to"] == "#DateTo"

    def test_search_form_fields_include_name_selectors(self) -> None:
        field_map = {attr: selector for attr, selector, _ in _NC_SEARCH_FORM_FIELDS}
        assert field_map["last_name"] == "#LastName"
        assert field_map["first_name"] == "#FirstName"

    def test_search_form_fields_include_org_name_selector(self) -> None:
        field_map = {attr: selector for attr, selector, _ in _NC_SEARCH_FORM_FIELDS}
        assert field_map["org_name"] == "#OrgName"
