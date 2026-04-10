"""Contract tests for write_scraper.md prompt artifact.

Validates that the prompt contains all required sections, mode-selection rules,
artifact paths, fixture/test requirements, politeness rules, known failure modes,
and example I/O pairs mandated by the Stage 6 checklist.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "write_scraper.md"


@lru_cache(maxsize=1)
def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _section_headings(text: str) -> list[str]:
    """Extract markdown heading text (any level)."""
    return [m.group(1).strip() for m in re.finditer(r"^#{1,4}\s+(.+)$", text, re.MULTILINE)]


def _section_body(section_heading: str) -> str:
    """Return the markdown body for a level-two section."""
    section_match = re.search(
        rf"^##\s+{re.escape(section_heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        _load_prompt(),
        re.MULTILINE | re.DOTALL,
    )
    assert section_match, f"Missing section: {section_heading}"
    return section_match.group("body")


def _subsection_body(section_heading: str, subsection_heading: str) -> str:
    """Return the markdown body for a level-three subsection inside one section."""
    subsection_match = re.search(
        rf"^###\s+{re.escape(subsection_heading)}\s*$\n(?P<body>.*?)(?=^###\s+|\Z)",
        _section_body(section_heading),
        re.MULTILINE | re.DOTALL,
    )
    assert subsection_match, f"Missing subsection: {subsection_heading}"
    return subsection_match.group("body")


def _mode_selection_row(format_value: str) -> tuple[str, str]:
    """Return the mode and script-path cells for a format row in the mode table."""
    row_match = re.search(
        rf"^\|\s*`{re.escape(format_value)}`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$",
        _section_body("Expected Output Format"),
        re.MULTILINE | re.IGNORECASE,
    )
    assert row_match, f"Missing `{format_value}` mode-selection row in format table"
    return row_match.group(1).strip(), row_match.group(2).strip()


def _unsupported_mode_row(row_label: str) -> tuple[str, str]:
    """Return the mode and script-path cells for an unsupported-format row."""
    row_match = re.search(
        rf"^\|\s*{re.escape(row_label)}\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$",
        _section_body("Expected Output Format"),
        re.MULTILINE | re.IGNORECASE,
    )
    assert row_match, f"Missing unsupported-format row: {row_label}"
    return row_match.group(1).strip(), row_match.group(2).strip()


class TestRequiredSections:
    """Prompt must contain all repo-standard sections per checklist item 3."""

    REQUIRED_SECTIONS = [
        "purpose",
        "expected input",
        "expected output",
        "politeness",
        "known failure mode",
        "completion criteria",
        "example",
    ]

    def test_prompt_file_exists(self):
        assert PROMPT_PATH.exists(), f"Prompt file missing at {PROMPT_PATH}"

    def test_all_required_sections_present(self):
        headings_lower = [h.lower() for h in _section_headings(_load_prompt())]
        for keyword in self.REQUIRED_SECTIONS:
            assert any(keyword in h for h in headings_lower), (
                f"Missing required section containing '{keyword}' in headings: {headings_lower}"
            )


class TestConsumerAndScope:
    """Prompt must name scrape_agent.py as consumer and exclude normalization/ingest."""

    def test_names_scrape_agent_as_consumer(self):
        text = _load_prompt()
        assert "scrape_agent.py" in text

    def test_excludes_normalization_and_ingest(self):
        text = _load_prompt().lower()
        assert "not normalization" in text
        assert "not ingest" in text


class TestModeSelection:
    """Prompt must define mode selection based on data_sources[].format."""

    def test_csv_mode_yields_direct_download(self):
        mode, script_path = _mode_selection_row("csv")
        assert "direct download" in mode.lower()
        assert script_path == "`scraper/download.py`"

    def test_web_portal_yields_playwright(self):
        mode, script_path = _mode_selection_row("web_portal")
        assert "playwright" in mode.lower()
        assert script_path == "`scraper/scrape.py`"

    def test_api_mode_yields_direct_download(self):
        mode, script_path = _mode_selection_row("api")
        assert "direct download" in mode.lower()
        assert script_path == "`scraper/download.py`"

    def test_fail_closed_for_unsupported_format(self):
        mode, script_path = _unsupported_mode_row("anything else")
        expected_output = _section_body("Expected Output Format").lower()
        assert "fail closed" in mode.lower()
        assert script_path == "No script generated"
        assert "unsupported or manual-only formats" in expected_output

    def test_pdf_mode_fails_closed(self):
        mode, script_path = _unsupported_mode_row("`pdf`")
        assert "fail closed" in mode.lower()
        assert script_path == "No script generated"


class TestDataSourcesContract:
    """Prompt must reference jurisdiction-config.md, not redefine the schema."""

    def test_references_jurisdiction_config(self):
        text = _section_body("Expected Input Format")
        assert "jurisdiction-config.md" in text

    def test_names_required_fields(self):
        text = _section_body("Expected Input Format")
        required_fields = ["name", "url", "format", "auth_required"]
        for field in required_fields:
            assert field in text, f"Missing data_sources field reference: {field}"

    def test_fail_closed_includes_auth_required(self):
        """The fail-closed rule must explicitly list auth_required as a required key."""
        text = _section_body("Expected Input Format")
        # Find the fail-closed sentence and verify auth_required appears in it
        fail_closed_match = re.search(r"fail.closed.*?stop\.", text, re.IGNORECASE | re.DOTALL)
        assert fail_closed_match, "No fail-closed rule found in prompt"
        fail_closed_text = fail_closed_match.group(0)
        assert "auth_required" in fail_closed_text, "Fail-closed rule does not mention auth_required as a required key"


class TestArtifactContract:
    """Prompt must specify exact output artifacts with consistent language/path convention."""

    def test_scraper_script_path(self):
        text = _section_body("Expected Output Format")
        # Must mention download.py for csv/api and scrape.py for web_portal
        assert "`scraper/download.py`" in text
        assert "`scraper/scrape.py`" in text

    def test_fixture_path(self):
        text = _section_body("Expected Output Format")
        assert "`scraper/test_data/`" in text

    def test_test_file_path(self):
        text = _section_body("Expected Output Format")
        assert "`scraper/test_scraper.py`" in text

    def test_consistent_language_python(self):
        """All scraper artifacts must be Python — no TypeScript/JS mixed in."""
        text = _section_body("Expected Output Format")
        assert ".py" in text
        assert not re.search(r"`[^`]+\.ts`", text), "Generated artifact contract must not include TypeScript file paths"

    def test_scraper_path_override_contract(self):
        """Artifact contract must handle data_sources[].scraper override and path reporting."""
        text = _subsection_body("Expected Output Format", "Artifact Contract")
        assert "data_sources[].scraper" in text
        text_lower = text.lower()
        assert "relative path rooted under the jurisdiction's `scraper/` directory" in text, (
            "Artifact contract must require scraper override paths to stay within scraper/"
        )
        assert "reject absolute paths" in text_lower and "`..`" in text, (
            "Artifact contract must reject absolute paths and parent-directory traversal"
        )
        assert "use the configured `data_sources[].scraper` path exactly as written" in text, (
            "Artifact contract must only use preset scraper paths after validation"
        )
        assert "report" in text_lower, (
            "Artifact contract must require reporting the chosen path when scraper field is absent"
        )

    def test_invalid_scraper_override_path_fails_closed(self):
        """Preset scraper paths must fail closed when they escape scraper/."""
        text = _subsection_body("Expected Output Format", "Artifact Contract").lower()
        assert "fail closed" in text
        assert "invalid path" in text
        assert "escapes the `scraper/` directory" in text or "escapes the scraper/ directory" in text


class TestFixtureRequirements:
    """Prompt must define fixture requirements for each mode."""

    def test_csv_api_fixture_record_count(self):
        text = _section_body("Expected Output Format")
        assert re.search(r"20[–-]50 representative records", text)

    def test_web_portal_fixture_is_sufficient_for_selectors_pagination_and_parsing(self):
        text = _subsection_body("Expected Output Format", "Artifact Contract")
        text_lower = text.lower()
        assert "web portal mode" in text_lower
        assert "html" in text_lower or "json api response" in text_lower or "raw response" in text_lower
        assert re.search(r"selectors,\s*pagination,\s*and parsing", text_lower), (
            "Web-portal fixture contract must explicitly require sufficiency for selectors, pagination, and parsing"
        )


class TestGeneratedTestRequirements:
    """Prompt must define test requirements: fixture-based, no live network by default."""

    def test_tests_run_against_fixture(self):
        text = _section_body("Expected Output Format").lower()
        assert "runs against the saved fixture by default" in text

    def test_no_live_network_by_default(self):
        text = _section_body("Expected Output Format").lower()
        assert "no live network access" in text

    def test_generated_test_verifies_expected_output_shape(self):
        text = _section_body("Expected Output Format").lower()
        assert "expected output shape" in text


class TestRawSourceFidelity:
    """Prompt must require raw-source fidelity and scrape metadata."""

    def test_requires_no_schema_transformation(self):
        text = _subsection_body("Constraints and Politeness Rules", "Raw-Source Fidelity").lower()
        assert "raw" in text or "as-is" in text or "fidelity" in text

    def test_requires_scrape_metadata(self):
        text = _subsection_body("Constraints and Politeness Rules", "Raw-Source Fidelity").lower()
        metadata_fields = ["source url", "timestamp", "record count", "file count", "warnings"]
        for field in metadata_fields:
            assert field in text, f"Missing scrape metadata field: {field}"


class TestRetryAndErrorHandling:
    """Prompt must specify retry and error handling requirements."""

    def test_mentions_retry(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "retry" in text or "retries" in text

    def test_mentions_timeout(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "timeout" in text

    def test_mentions_http_error_codes(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "4xx" in text or "5xx" in text or "status code" in text

    def test_pagination_termination(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "pagination" in text

    def test_duplicate_page_guard(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "duplicate" in text

    def test_empty_result_handling(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "empty result" in text

    def test_partial_download_handling(self):
        text = _subsection_body("Constraints and Politeness Rules", "Retry and Error Handling").lower()
        assert "partial download" in text


class TestEncodingAndMalformedData:
    """Prompt must handle encoding issues common in government exports."""

    def test_mentions_encoding(self):
        text = _subsection_body(
            "Constraints and Politeness Rules",
            "Encoding and Malformed Data Handling",
        ).lower()
        assert "encoding" in text or "utf-8" in text or "utf8" in text

    def test_mentions_bom(self):
        text = _subsection_body(
            "Constraints and Politeness Rules",
            "Encoding and Malformed Data Handling",
        ).lower()
        assert "bom" in text

    def test_mentions_delimiter_issues(self):
        text = _subsection_body(
            "Constraints and Politeness Rules",
            "Encoding and Malformed Data Handling",
        ).lower()
        assert "delimiter" in text

    def test_header_drift(self):
        text = _subsection_body(
            "Constraints and Politeness Rules",
            "Encoding and Malformed Data Handling",
        ).lower()
        assert "header drift" in text

    def test_malformed_rows(self):
        text = _subsection_body(
            "Constraints and Politeness Rules",
            "Encoding and Malformed Data Handling",
        ).lower()
        assert "malformed rows" in text


class TestPolitenessRules:
    """Prompt must encode politeness and compliance rules."""

    def test_request_delay(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "delay" in text or "throttl" in text or "rate" in text

    def test_bounded_concurrency(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "bounded concurrency" in text

    def test_terms_of_service(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "terms of service" in text

    def test_robots_txt(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "robots.txt" in text or "robots" in text

    def test_user_agent(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "user-agent" in text or "user agent" in text

    def test_no_bypass_auth_or_captcha(self):
        text = _subsection_body("Constraints and Politeness Rules", "Politeness and Compliance").lower()
        assert "captcha" in text and ("bypass" in text or "never" in text)


class TestKnownFailureModes:
    """Prompt must have a known failure modes section."""

    REQUIRED_FAILURE_MODES = [
        "csrf",
        "signed url",
        "cookie",
        "js-rendered",
        "selector",
        "pop-up",
        "outage",
    ]

    def test_failure_modes_section_exists(self):
        headings = [h.lower() for h in _section_headings(_load_prompt())]
        assert any("failure" in h or "known" in h for h in headings)

    def test_covers_required_failure_modes(self):
        text = _section_body("Known Failure Modes").lower()
        for mode in self.REQUIRED_FAILURE_MODES:
            assert mode.replace("-", "") in text.replace("-", ""), f"Missing known failure mode: {mode}"


class TestEscalationRules:
    """Prompt must tell the agent when to stop and escalate."""

    def test_escalation_on_captcha(self):
        text = _section_body("Escalation Rules — When to Stop").lower()
        assert "captcha" in text and "escalat" in text

    def test_escalation_on_login_required(self):
        text = _section_body("Escalation Rules — When to Stop").lower()
        assert "login required without provided credentials" in text

    def test_escalation_on_manual_steps(self):
        text = _section_body("Escalation Rules — When to Stop").lower()
        assert "required human download steps" in text

    def test_escalation_on_selector_ambiguity(self):
        text = _section_body("Escalation Rules — When to Stop").lower()
        assert "irreducible selector ambiguity" in text

    def test_escalation_on_portal_changes(self):
        text = _section_body("Escalation Rules — When to Stop").lower()
        assert "portal changes that break repeatability" in text


class TestLiveVerification:
    """Prompt must require live verification before declaring success."""

    def test_live_verification_required(self):
        text = _subsection_body("Completion Criteria", "Live Verification").lower()
        assert "live" in text and "verif" in text

    def test_minimum_evidence_fields(self):
        text = _subsection_body("Completion Criteria", "Live Verification").lower()
        evidence_fields = ["url", "date", "rows", "files", "caveats"]
        for field in evidence_fields:
            assert field in text, f"Missing live-verification evidence field: {field}"


class TestExampleIOPairs:
    """Prompt must contain at least two example I/O pairs."""

    def test_has_csv_or_api_example(self):
        text = _section_body("Example Input/Output Pairs").lower()
        assert "csv" in text or "api" in text

    def test_has_web_portal_example(self):
        text = _section_body("Example Input/Output Pairs").lower()
        assert "web_portal" in text

    def test_web_portal_example_fixture_mentions_pagination(self):
        text = _subsection_body(
            "Example Input/Output Pairs",
            "Example 2: Web Portal Scraper (NC State Board of Elections)",
        ).lower()
        assert "captured_page.html" in text
        assert "pagination" in text

    def test_at_least_two_examples(self):
        text = _load_prompt()
        # Count only numbered example headings (e.g., "Example 1: ...", "Example 2: ..."),
        # not the parent "Example Input/Output Pairs" section heading.
        example_headings = [h for h in _section_headings(text) if re.search(r"example\s+\d", h, re.IGNORECASE)]
        assert len(example_headings) >= 2, (
            f"Need at least 2 numbered example I/O headings, found {len(example_headings)}: {example_headings}"
        )
