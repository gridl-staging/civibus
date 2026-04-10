
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import tempfile

from domains.campaign_finance.jurisdictions.states.IL.scraper import (
    _load_bulk_download_url_for_data_type as il_bulk_download_url_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.IL.scraper import (
    _load_column_for_semantic_path as il_column_for_semantic_path,
)
from domains.campaign_finance.jurisdictions.states.IL.scraper import (
    _load_data_source_url_for_data_type as il_data_source_url_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.IL.scraper.download import download_il_data
from domains.campaign_finance.jurisdictions.states.IL.scraper.load import _parse_il_date as parse_il_date
from domains.campaign_finance.jurisdictions.states.IL.scraper.parse import (
    parse_contributions as parse_il_contributions,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper import (
    _load_bulk_download_url_for_data_type as in_bulk_download_url_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper import (
    _load_column_for_semantic_path as in_column_for_semantic_path,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper import (
    _load_data_source_for_data_type as in_data_source_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.download import download_in_data
from domains.campaign_finance.jurisdictions.states.IN.scraper.load_helpers import _parse_in_date as parse_in_date
from domains.campaign_finance.jurisdictions.states.IN.scraper.parse import (
    parse_contributions as parse_in_contributions,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper import (
    _load_column_for_semantic_path as mn_column_for_semantic_path,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper import (
    _load_data_source_url_for_data_type as mn_source_url_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper.download import (
    build_mn_download_url,
    download_mn_csv,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper.load import _parse_optional_mn_date as parse_mn_date
from domains.campaign_finance.jurisdictions.states.MN.scraper.parse import (
    parse_contributions as parse_mn_contributions,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper import (
    _load_column_for_semantic_path as nj_column_for_semantic_path,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper import (
    _load_data_source_url_for_data_type as nj_source_url_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper.download import (
    build_nj_download_url,
    download_nj_csv,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load import _parse_nj_date as parse_nj_date
from domains.campaign_finance.jurisdictions.states.NJ.scraper.parse import (
    parse_contributions as parse_nj_contributions,
)

from .models import CheckResult, CheckStatus, JurisdictionSummary

_PASS_MAX_AGE_DAYS = 7
_WARN_MAX_AGE_DAYS = 30
_IL_FRESHNESS_TAIL_ROWS = 50_000


@dataclass(frozen=True, slots=True)
class _FreshnessProbeConfig:
    jurisdiction: str
    probe_check: Callable[[], CheckResult]
    source_url: Callable[[], str]


@dataclass(frozen=True, slots=True)
class _ContributionsProbeConfig:

    jurisdiction: str
    temp_dir_prefix: str
    load_date_column: Callable[[], str]
    load_source_url: Callable[[], str]
    load_artifact_url: Callable[[], str]
    download_to_dir: Callable[[Path], Path]
    parse_rows: Callable[[Path], Iterable[Mapping[str, str | None]]]
    parse_date: Callable[[str | None], date | None]

    def observe(self, *, as_of_date: date | None = None) -> _FreshnessObservation:
        date_column = self.load_date_column()
        source_url = self.load_source_url()
        artifact_url = self.load_artifact_url()

        with tempfile.TemporaryDirectory(prefix=self.temp_dir_prefix) as temp_dir:
            temp_dir_path = Path(temp_dir).resolve()
            download_path = self.download_to_dir(temp_dir_path).resolve(strict=False)
            # Keep downloader outputs confined to the per-run temp directory before parsing.
            if not download_path.is_relative_to(temp_dir_path):
                raise ValueError(f"{self.jurisdiction}: downloader path escaped the temporary directory")
            rows = self.parse_rows(download_path)
            max_transaction_date, parsed_row_count, future_dated_row_count, max_future_transaction_date = (
                _max_transaction_date_from_rows(
                    rows,
                    date_column=date_column,
                    parse_date=self.parse_date,
                    as_of_date=as_of_date,
                )
            )

        return _FreshnessObservation(
            jurisdiction=self.jurisdiction,
            source_url=source_url,
            artifact_url=artifact_url,
            date_column=date_column,
            parsed_row_count=parsed_row_count,
            max_transaction_date=max_transaction_date,
            future_dated_row_count=future_dated_row_count,
            max_future_transaction_date=max_future_transaction_date,
        )


@dataclass(frozen=True, slots=True)
class _FreshnessObservation:

    jurisdiction: str
    source_url: str
    artifact_url: str
    date_column: str
    parsed_row_count: int
    max_transaction_date: date | None
    future_dated_row_count: int = 0
    max_future_transaction_date: date | None = None

    def details(self, *, as_of_date: date | None = None) -> dict[str, str | int | None]:
        details: dict[str, str | int | None] = {
            "max_transaction_date": None,
            "date_column": self.date_column,
            "parsed_row_count": self.parsed_row_count,
            "source_url": self.source_url,
            "artifact_url": self.artifact_url,
            "future_dated_row_count": self.future_dated_row_count,
            "max_future_transaction_date": None,
        }
        if self.max_transaction_date is not None:
            details["max_transaction_date"] = self.max_transaction_date.isoformat()
        if self.max_future_transaction_date is not None:
            details["max_future_transaction_date"] = self.max_future_transaction_date.isoformat()
        if as_of_date is not None:
            details["as_of_date"] = as_of_date.isoformat()
        return details


def _dedupe(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _freshness_status_for_age_days(age_days: int) -> CheckStatus:
    if age_days < 0:
        return "warn"
    if age_days <= _PASS_MAX_AGE_DAYS:
        return "pass"
    if age_days <= _WARN_MAX_AGE_DAYS:
        return "warn"
    return "fail"


def _max_transaction_date_from_rows(
    rows: Iterable[Mapping[str, str | None]],
    *,
    date_column: str,
    parse_date: Callable[[str | None], date | None],
    as_of_date: date | None = None,
) -> tuple[date | None, int, int, date | None]:
    max_transaction_date: date | None = None
    parsed_row_count = 0
    effective_as_of = as_of_date or date.today()
    future_dated_row_count = 0
    max_future_transaction_date: date | None = None

    for row in rows:
        parsed_row_count += 1
        parsed_date = parse_date(row.get(date_column))
        if parsed_date is None:
            continue
        # Government exports occasionally contain obviously future-dated outliers.
        # We surface them in the details payload, but they should not define
        # recency for the whole source.
        if parsed_date > effective_as_of:
            future_dated_row_count += 1
            if max_future_transaction_date is None or parsed_date > max_future_transaction_date:
                max_future_transaction_date = parsed_date
            continue
        if max_transaction_date is None or parsed_date > max_transaction_date:
            max_transaction_date = parsed_date

    return max_transaction_date, parsed_row_count, future_dated_row_count, max_future_transaction_date


def _build_freshness_check_result(
    observation: _FreshnessObservation,
    as_of_date: date | None = None,
) -> CheckResult:
    if observation.max_transaction_date is None:
        message = f"{observation.jurisdiction}: no parseable transaction dates found in {observation.date_column}"
        if observation.future_dated_row_count:
            message = (
                f"{observation.jurisdiction}: no non-future transaction dates found in {observation.date_column}; "
                f"ignored {observation.future_dated_row_count} future-dated rows"
            )
        return CheckResult(
            name="freshness",
            status="fail",
            message=message,
            metric_name="max_transaction_age_days",
            metric_value=None,
            threshold=float(_PASS_MAX_AGE_DAYS),
            details=observation.details(),
        )

    effective_as_of = as_of_date or date.today()
    age_days = (effective_as_of - observation.max_transaction_date).days
    status = _freshness_status_for_age_days(age_days)
    message = (
        f"{observation.jurisdiction}: max {observation.date_column}={observation.max_transaction_date.isoformat()} "
        f"({age_days} days old as of {effective_as_of.isoformat()})"
    )
    if observation.future_dated_row_count:
        message = (
            f"{message}; ignored {observation.future_dated_row_count} future-dated rows "
            f"(max future date {observation.max_future_transaction_date.isoformat()})"
        )
    return CheckResult(
        name="freshness",
        status=status,
        message=message,
        metric_name="max_transaction_age_days",
        metric_value=float(age_days),
        threshold=float(_PASS_MAX_AGE_DAYS),
        details=observation.details(as_of_date=effective_as_of),
    )


def _probe_contributions(config: _ContributionsProbeConfig) -> CheckResult:
    effective_as_of = date.today()
    return _build_freshness_check_result(config.observe(as_of_date=effective_as_of), as_of_date=effective_as_of)


def _probe_il_contributions() -> CheckResult:
    """Probe Illinois contributions using the same bulk-export path as production loads.

    Illinois is the odd one out among the freshness states: the source file is
    generated behind an ASP.NET postback flow instead of living at a static URL.
    Reusing the production downloader keeps the probe aligned with the proven
    contract instead of duplicating the portal handshake in quality code.

    The repo's Illinois freshness research already established that `Receipts.txt`
    is ordered by ascending IDs, with recent filings at the tail of the file.
    Keeping only the trailing slice lets the probe stay bounded while still
    measuring current recency against the production export contract.
    """
    return _probe_contributions(
        _ContributionsProbeConfig(
            jurisdiction="state/IL",
            temp_dir_prefix="quality-freshness-il-",
            load_date_column=lambda: il_column_for_semantic_path("contributions", "transaction.date"),
            load_source_url=lambda: il_data_source_url_for_data_type("contributions"),
            load_artifact_url=lambda: il_bulk_download_url_for_data_type("contributions"),
            download_to_dir=lambda destination_dir: download_il_data(
                "contributions",
                dest_dir=destination_dir,
                tail_data_rows=_IL_FRESHNESS_TAIL_ROWS,
            ),
            parse_rows=parse_il_contributions,
            parse_date=parse_il_date,
        )
    )


def _probe_in_contributions() -> CheckResult:
    year = date.today().year
    return _probe_contributions(
        _ContributionsProbeConfig(
            jurisdiction="state/IN",
            temp_dir_prefix="quality-freshness-in-",
            load_date_column=lambda: in_column_for_semantic_path("contributions", "transaction.date"),
            load_source_url=lambda: in_data_source_for_data_type("contributions").url,
            load_artifact_url=lambda: in_bulk_download_url_for_data_type("contributions").replace("{YEAR}", str(year)),
            download_to_dir=lambda destination_dir: download_in_data(
                year=year,
                data_type="contributions",
                dest_dir=destination_dir,
            ),
            parse_rows=parse_in_contributions,
            parse_date=parse_in_date,
        )
    )


def _probe_mn_contributions() -> CheckResult:
    return _probe_contributions(
        _ContributionsProbeConfig(
            jurisdiction="state/MN",
            temp_dir_prefix="quality-freshness-mn-",
            load_date_column=lambda: mn_column_for_semantic_path("contributions", "transaction.date"),
            load_source_url=lambda: mn_source_url_for_data_type("contributions"),
            load_artifact_url=lambda: build_mn_download_url("contributions"),
            download_to_dir=lambda destination_dir: download_mn_csv(
                data_type="contributions",
                dest_dir=destination_dir,
            ),
            parse_rows=parse_mn_contributions,
            parse_date=parse_mn_date,
        )
    )


def _probe_nj_contributions() -> CheckResult:
    return _probe_contributions(
        _ContributionsProbeConfig(
            jurisdiction="state/NJ",
            temp_dir_prefix="quality-freshness-nj-",
            load_date_column=lambda: nj_column_for_semantic_path("contributions", "transaction.date"),
            load_source_url=lambda: nj_source_url_for_data_type("contributions"),
            load_artifact_url=lambda: build_nj_download_url("contributions"),
            download_to_dir=lambda destination_dir: download_nj_csv(
                data_type="contributions",
                dest_dir=destination_dir,
            ),
            parse_rows=parse_nj_contributions,
            parse_date=parse_nj_date,
        )
    )


_PROBE_REGISTRY: tuple[_FreshnessProbeConfig, ...] = (
    _FreshnessProbeConfig(
        jurisdiction="state/IL",
        probe_check=lambda: _probe_il_contributions(),
        source_url=lambda: il_data_source_url_for_data_type("contributions"),
    ),
    _FreshnessProbeConfig(
        jurisdiction="state/IN",
        probe_check=lambda: _probe_in_contributions(),
        source_url=lambda: in_data_source_for_data_type("contributions").url,
    ),
    _FreshnessProbeConfig(
        jurisdiction="state/MN",
        probe_check=lambda: _probe_mn_contributions(),
        source_url=lambda: mn_source_url_for_data_type("contributions"),
    ),
    _FreshnessProbeConfig(
        jurisdiction="state/NJ",
        probe_check=lambda: _probe_nj_contributions(),
        source_url=lambda: nj_source_url_for_data_type("contributions"),
    ),
)


def _probe_configs_for_jurisdiction(jurisdiction_filter: str | None) -> tuple[_FreshnessProbeConfig, ...]:
    if jurisdiction_filter is None:
        return _PROBE_REGISTRY
    return tuple(config for config in _PROBE_REGISTRY if config.jurisdiction == jurisdiction_filter)


def run_freshness_checks(jurisdiction_filter: str | None) -> list[JurisdictionSummary]:
    summaries: list[JurisdictionSummary] = []
    for probe_config in _probe_configs_for_jurisdiction(jurisdiction_filter):
        baseline_urls: list[str] = []
        try:
            baseline_urls.append(probe_config.source_url())
        except Exception:
            baseline_urls = []

        try:
            check_result = probe_config.probe_check()
        except Exception as error:  # noqa: BLE001
            check_result = CheckResult(
                name="freshness",
                status="error",
                message=f"{probe_config.jurisdiction}: freshness probe failed: {error}",
                details={"error": str(error)},
            )

        source_url = check_result.details.get("source_url")
        if isinstance(source_url, str):
            baseline_urls.append(source_url)

        summaries.append(
            JurisdictionSummary(
                jurisdiction=probe_config.jurisdiction,
                baseline_urls=_dedupe(baseline_urls),
                check_results=[check_result],
            )
        )

    return summaries
