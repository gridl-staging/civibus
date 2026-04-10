"""Pydantic result models for quality checks and reconciliation.

These models define the single JSON schema consumed by the CLI.
Do not create separate contract documents — this module is the source of truth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


CheckStatus = Literal["pass", "fail", "warn", "error"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CheckResult(BaseModel, extra="forbid"):
    """Outcome of a single quality check."""

    name: str
    status: CheckStatus
    message: str = ""
    metric_name: str = ""
    metric_value: float | None = None
    threshold: float | None = None
    details: dict[str, object] = Field(default_factory=dict)

    def is_passing(self) -> bool:
        return self.status in ("pass", "warn")


class JurisdictionSummary(BaseModel, extra="forbid"):
    """Aggregated quality results for one jurisdiction."""

    jurisdiction: str
    data_source_ids: list[str] = Field(default_factory=list)
    baseline_urls: list[str] = Field(default_factory=list)
    record_count: int = 0
    check_results: list[CheckResult] = Field(default_factory=list)

    @property
    def status(self) -> CheckStatus:
        if not self.check_results:
            return "pass"
        statuses = {r.status for r in self.check_results}
        if "error" in statuses:
            return "error"
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.check_results if r.status == "pass")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.check_results if r.status == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.check_results if r.status == "warn")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.check_results if r.status == "error")


class QualityReport(BaseModel, extra="forbid"):
    """Top-level quality report emitted by the CLI as JSON."""

    generated_at: datetime = Field(default_factory=_utc_now)
    jurisdiction_filter: str | None = None
    check_filter: str | None = None
    summaries: list[JurisdictionSummary] = Field(default_factory=list)

    @property
    def status(self) -> CheckStatus:
        if not self.summaries:
            return "pass"
        statuses = {s.status for s in self.summaries}
        if "error" in statuses:
            return "error"
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    @property
    def total_checks(self) -> int:
        return sum(len(s.check_results) for s in self.summaries)

    @property
    def total_pass(self) -> int:
        return sum(s.pass_count for s in self.summaries)

    @property
    def total_fail(self) -> int:
        return sum(s.fail_count for s in self.summaries)

    def to_json(self) -> str:
        """Serialize to deterministic JSON for CLI output."""
        data = self.model_dump(mode="json")
        data["status"] = self.status
        for i, summary in enumerate(self.summaries):
            data["summaries"][i]["status"] = summary.status
            data["summaries"][i]["pass_count"] = summary.pass_count
            data["summaries"][i]["fail_count"] = summary.fail_count
            data["summaries"][i]["warn_count"] = summary.warn_count
            data["summaries"][i]["error_count"] = summary.error_count
        data["total_checks"] = self.total_checks
        data["total_pass"] = self.total_pass
        data["total_fail"] = self.total_fail
        import json

        return json.dumps(data, indent=2, sort_keys=False)
