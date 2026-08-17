"""Shared fixtures for deployed public-surface parity probe contracts."""

from __future__ import annotations

import csv
import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "infra/scripts/probe_deployed_surface_parity.sh"
MANIFEST_PATH = REPO_ROOT / "infra/public_surface_probes.tsv"
EXPECTED_PRODUCTION_MANIFEST_READERS = frozenset(
    {
        ".github/workflows/uptime_probe.yml",
        "infra/scripts/probe_deployed_surface_parity.sh",
    }
)
MANIFEST_HEADER = (
    "surface_id",
    "kind",
    "path",
    "marker",
    "parity_mode",
    "uptime_mode",
    "owners",
)
KNOWN_SURFACE_KINDS = frozenset({"static", "person_sitemap"})
KNOWN_PARITY_MODES = frozenset({"fatal", "known_red", "skip"})
KNOWN_UPTIME_MODES = frozenset({"fatal", "skip"})
STATIC_SURFACE_IDS = (
    "home_surface",
    "search_surface",
    "donor_search_surface",
    "congress_surface",
    "methodology_surface",
    "developers_surface",
    "candidates_surface",
    "committees_surface",
    "committee_detail_surface",
    "compare_surface",
    "calendar_surface",
    "coverage_surface",
    "data_sources_surface",
    "sitemap_index_surface",
)
RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/fly_deployment_runbook.md"
RELEASE_TARGETS_PATH = REPO_ROOT / "web/tests/smoke/production_release_targets.json"
DEFAULT_PUBLIC_BASE_URL = "https://civibus-caddy.fly.dev"
PERSON_SURFACE_SITEMAP_PATH = "/sitemap-person-0.xml"
PERSON_SURFACE_UUID = "22222222-2222-4222-8222-222222222222"
PERSON_SURFACE_PATH = f"/person/{PERSON_SURFACE_UUID}"
PERSON_SURFACE_MARKER = 'aria-label="Breadcrumb"'
EXPECTED_SHA = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPO_ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
DRIFTED_SHA = subprocess.run(
    ["git", "rev-parse", "HEAD~1"],
    cwd=REPO_ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()

PUBLIC_PAGE_BODIES = {
    "/": "Follow money around Congress and the White House.",
    "/search?q=ossoff": 'data-testid="search-results-region"',
    "/donors?q=smith&by=name": 'data-testid="donor-result-row"',
    "/congress": 'data-testid="congress-member-row-0"',
    "/methodology": "Methodology",
    "/developers": "GET /api/public/v1/federal/officials",
    "/candidates": "Candidates",
    "/committees": "Committees",
    "/committee/jon-ossoff-for-senate": "Key metrics",
    "/compare": "Compare officeholders",
    "/calendar": "Election calendar",
    "/coverage": "campaign_finance",
    "/data-sources": "campaign_finance",
    "/sitemap.xml": "<sitemapindex",
}
KNOWN_RED_PAGE_BODIES = {
    PERSON_SURFACE_SITEMAP_PATH: (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{DEFAULT_PUBLIC_BASE_URL}{PERSON_SURFACE_PATH}</loc></url>"
        "</urlset>"
    ),
    PERSON_SURFACE_PATH: f"<html><nav {PERSON_SURFACE_MARKER}>Member</nav></html>",
}
DEFAULT_PAGE_BODIES = PUBLIC_PAGE_BODIES | KNOWN_RED_PAGE_BODIES

_NON_PRODUCTION_TOP_LEVELS = frozenset({"decisions", "docs", "tests"})
_NON_PRODUCTION_PATH_TOKENS = frozenset({"artifacts"})
_ROOT_DOCUMENTATION_FILES = frozenset(
    {
        "AGENTS.md",
        "BEADS_QA_TRANSITION.md",
        "CAPABILITIES.md",
        "CLAUDE.md",
        "CODE_MAP.md",
        "DIRMAP.md",
        "PROJECT_OVERVIEW.md",
        "README.md",
        "ROADMAP.md",
    }
)
_PUBLIC_SURFACE_HOSTS = ("civibus-caddy.fly.dev", "civibus.shareborough.com")
_PUBLIC_SURFACE_URL = re.compile(
    r"https?://(?:" + "|".join(re.escape(host) for host in _PUBLIC_SURFACE_HOSTS) + r")(?P<route>/[^\s\"'`)}]*)"
)
_INTERPOLATED_PUBLIC_SURFACE_ROUTE = re.compile(
    r"(?:\$\{(?=[^}]*BASE_URL)[^}]+}|\$\((?=[^)]*base_url)[^)]+\))(?P<route>/[^\s\"'`]*)",
    re.IGNORECASE,
)
# Health, deploy-drift, and version routes are owned outside the manifest and
# are not public surfaces, so a literal reference to one is not a bypass.
_NON_SURFACE_ROUTE_PREFIXES = ("/api/", "/health", "/version", "/.well-known")
# A metadata name can be introduced by a shell declaration qualifier
# (``readonly NAME=``, ``declare -r NAME=``) or sit under a YAML sequence dash,
# so the leading token is optional and never part of the captured name.
_SHELL_OR_YAML_ASSIGNMENT = re.compile(
    r"^\s*(?:-\s+)?"
    r"(?:(?:readonly|export|local|declare|typeset)\s+(?:-[A-Za-z]+\s+)*)?"
    r"(?P<name>[A-Z][A-Z0-9_]*)\s*(?:=|:)\s*(?P<value>.+?)\s*$"
)
_SURFACE_METADATA_SUFFIXES = (
    "PARITY_MODE",
    "UPTIME_MODE",
    "SURFACE_ID",
    "MARKER",
    "OWNERS",
    "OWNER",
    "KIND",
    "PATH",
    "URL",
    "ID",
)
_QUOTED_SURFACE_ID = re.compile(r"(?P<quote>['\"])(?P<value>[a-z][a-z0-9_]*_surface)(?P=quote)")


def read_public_surface_manifest() -> list[dict[str, str]]:
    """Parse the committed TSV once for every repository-level contract."""
    with MANIFEST_PATH.open(encoding="utf-8", newline="") as manifest_file:
        manifest_rows = list(csv.reader(manifest_file, delimiter="\t"))

    assert manifest_rows, "public-surface manifest must contain its fixed header"
    assert tuple(manifest_rows[0]) == MANIFEST_HEADER
    parsed_rows: list[dict[str, str]] = []
    for row_number, fields in enumerate(manifest_rows[1:], start=2):
        assert len(fields) == len(MANIFEST_HEADER), (
            f"manifest row {row_number} has {len(fields)} fields; expected {len(MANIFEST_HEADER)}"
        )
        parsed_rows.append(dict(zip(MANIFEST_HEADER, fields, strict=True)))
    return parsed_rows


def assert_manifest_row_schema(parsed_rows: list[dict[str, str]]) -> None:
    """Assert each manifest row has non-blank required fields and known enums."""
    for row_number, row in enumerate(parsed_rows, start=2):
        for required_field in ("surface_id", "path", "marker", "owners"):
            assert row[required_field].strip(), f"manifest row {row_number} has blank {required_field}"
        assert row["kind"] in KNOWN_SURFACE_KINDS, f"manifest row {row_number} has unknown kind={row['kind']}"
        assert row["parity_mode"] in KNOWN_PARITY_MODES, (
            f"manifest row {row_number} has unknown parity_mode={row['parity_mode']}"
        )
        assert row["uptime_mode"] in KNOWN_UPTIME_MODES, (
            f"manifest row {row_number} has unknown uptime_mode={row['uptime_mode']}"
        )


def assert_manifest_surface_topology(parsed_rows: list[dict[str, str]]) -> None:
    """Assert the committed manifest exposes the expected static and person surfaces."""
    surface_ids = [row["surface_id"] for row in parsed_rows]
    assert len(surface_ids) == len(set(surface_ids)), "manifest surface_id values must be unique"
    assert len(parsed_rows) == len(PUBLIC_PAGE_BODIES) + 1
    assert {row["path"] for row in parsed_rows} == set(PUBLIC_PAGE_BODIES) | {PERSON_SURFACE_SITEMAP_PATH}
    static_rows = [row for row in parsed_rows if row["kind"] == "static"]
    assert [(row["surface_id"], row["path"], row["uptime_mode"]) for row in static_rows] == [
        (surface_id, path, "fatal" if surface_id == "donor_search_surface" else "skip")
        for surface_id, path in zip(STATIC_SURFACE_IDS, PUBLIC_PAGE_BODIES, strict=True)
    ]
    assert {
        row["path"]: {"kind": row["kind"], "marker": row["marker"], "parity_mode": row["parity_mode"]}
        for row in parsed_rows
        if row["path"] in PUBLIC_PAGE_BODIES
    } == {
        path: {"kind": "static", "marker": marker, "parity_mode": "fatal"}
        for path, marker in PUBLIC_PAGE_BODIES.items()
    }

    person_rows = [row for row in parsed_rows if row["surface_id"] == "person_detail_surface"]
    assert len(person_rows) == 1
    assert {field: person_rows[0][field] for field in ("kind", "path", "marker", "parity_mode", "uptime_mode")} == {
        "kind": "person_sitemap",
        "path": PERSON_SURFACE_SITEMAP_PATH,
        "marker": 'aria-label="Breadcrumb"',
        "parity_mode": "known_red",
        "uptime_mode": "fatal",
    }


def _is_production_source_path(relative_path: Path) -> bool:
    if relative_path.parts[0] in _NON_PRODUCTION_TOP_LEVELS:
        return False
    if len(relative_path.parts) == 1 and relative_path.name in _ROOT_DOCUMENTATION_FILES:
        return False
    return not (_NON_PRODUCTION_PATH_TOKENS & set(relative_path.parts))


def _repository_source_paths() -> tuple[Path, ...]:
    """Every tracked or untracked production path, independent of file suffix.

    Suffix is not a proxy for production status: extensionless owners such as
    ``Makefile``, ``Dockerfile``, and ``infra/Caddyfile`` carry runtime
    behavior and must be discoverable here. Only established non-production
    locations are excluded; binary content is dropped later when bytes are read.
    """
    tracked_and_untracked = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    paths = []
    for encoded_path in tracked_and_untracked:
        if not encoded_path:
            continue
        relative_path = Path(os.fsdecode(encoded_path))
        if not _is_production_source_path(relative_path):
            continue
        paths.append(relative_path)
    return tuple(paths)


def _iter_production_text_sources() -> Iterator[tuple[Path, str]]:
    """Yield each production path with its decoded text, skipping binary files."""
    for relative_path in _repository_source_paths():
        raw = (REPO_ROOT / relative_path).read_bytes()
        if b"\x00" in raw:
            continue
        try:
            yield relative_path, raw.decode("utf-8")
        except UnicodeDecodeError:
            continue


def production_manifest_readers(
    sources: Iterable[tuple[Path, str]] | None = None,
) -> frozenset[str]:
    """Return production text files that read the public-surface TSV."""
    manifest_relative_path = MANIFEST_PATH.relative_to(REPO_ROOT)
    readers = set()
    for relative_path, source in sources if sources is not None else _iter_production_text_sources():
        if relative_path == manifest_relative_path:
            continue
        if MANIFEST_PATH.name in source:
            readers.add(relative_path.as_posix())
    return frozenset(readers)


def _literal_assignment_value(raw_value: str) -> str | None:
    value = raw_value.strip().rstrip(",")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if not value or any(token in value for token in ("${", "$(", "{{")):
        return None
    return value


def _is_non_surface_route(route: str) -> bool:
    return route.startswith(_NON_SURFACE_ROUTE_PREFIXES)


def _metadata_field_from_name(name: str) -> tuple[str, str] | None:
    if "MANIFEST" in name:
        return None
    for suffix in _SURFACE_METADATA_SUFFIXES:
        suffix_token = f"_{suffix}"
        if name.endswith(suffix_token):
            field = suffix.lower()
            if field == "surface_id" or field == "id":
                field = "surface_id"
            elif field == "owner":
                field = "owners"
            return name[: -len(suffix_token)], field
    return None


def _metadata_assignment(line: str) -> tuple[str, str, str] | None:
    assignment = _SHELL_OR_YAML_ASSIGNMENT.match(line)
    if assignment is None:
        return None
    metadata_field = _metadata_field_from_name(assignment.group("name"))
    if metadata_field is None:
        return None
    prefix, field = metadata_field
    return prefix, field, assignment.group("value")


def _surface_routes_in_value(value: str) -> set[str]:
    routes = {match.group("route") for match in _PUBLIC_SURFACE_URL.finditer(value)}
    routes.update(match.group("route") for match in _INTERPOLATED_PUBLIC_SURFACE_ROUTE.finditer(value))
    literal_value = _literal_assignment_value(value)
    if literal_value is not None and literal_value.startswith("/"):
        routes.add(literal_value)
    return routes


def _is_unregistered_surface_route(route: str, allowed: dict[str, set[str]]) -> bool:
    return not _is_non_surface_route(route) and route not in allowed["path"]


def _display_assignment_value(raw_value: str) -> str | None:
    return _literal_assignment_value(raw_value) or next(iter(sorted(_surface_routes_in_value(raw_value))), None)


def _unregistered_route_assignment_message(relative_path_text: str, line_number: int, field: str, route: str) -> str:
    label = "surface_url" if field == "url" else field
    return f"{relative_path_text}:{line_number} unregistered {label}={route}"


def _registration_mismatch_message(
    relative_path_text: str,
    line_number: int,
    route: str,
    field: str,
    value: str,
    expected_value: str,
) -> str:
    return (
        f"{relative_path_text}:{line_number} metadata_mismatch route={route} {field}={value} expected={expected_value}"
    )


def _has_shell_expansion(value: str) -> bool:
    """Detect runtime interpolation without treating single-quoted dollars as dynamic.

    The helper inspects one shell word at a time. Inside a word, ``#`` remains
    literal text, so it must not terminate scanning before a later expansion.
    """
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if character == "'" and quote != '"':
            quote = None if quote == "'" else "'"
            continue
        if character == '"' and quote != "'":
            quote = None if quote == '"' else '"'
            continue
        if value[index : index + 2] in {"{{", "}}"} or (quote != "'" and character in {"$", "`"}):
            return True
    return False


def _direct_probe_call_metadata(line: str) -> tuple[str, dict[str, str]] | None:
    stripped_line = line.strip()
    if re.match(r"^(?:probe_url|probe_public_page)(?:\s|$)", stripped_line) is None:
        return None

    raw_words: list[str] = []
    word_start: int | None = None
    quote: str | None = None
    escaped = False
    for index, character in enumerate(stripped_line):
        if word_start is None:
            if character.isspace():
                continue
            if character == "#":
                break
            word_start = index
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if character == "'" and quote != '"':
            quote = None if quote == "'" else "'"
            continue
        if character == '"' and quote != "'":
            quote = None if quote == '"' else '"'
            continue
        if character.isspace() and quote is None:
            raw_words.append(stripped_line[word_start:index])
            word_start = None
    if word_start is not None:
        raw_words.append(stripped_line[word_start:])

    try:
        decoded_words = [shlex.split(raw_word, comments=False, posix=True) for raw_word in raw_words]
    except ValueError:
        return None
    if any(len(decoded_word) != 1 for decoded_word in decoded_words):
        return None
    words = [decoded_word[0] for decoded_word in decoded_words]
    if len(words) >= 4 and words[0] == "probe_url":
        route_word_index = 2
        metadata_fields = (("surface_id", 1), ("marker", 3))
    elif len(words) >= 6 and words[0] == "probe_public_page":
        route_word_index = 1
        metadata_fields = (("path", 1), ("marker", 2), ("parity_mode", 3), ("surface_id", 4), ("owners", 5))
    else:
        return None
    if _has_shell_expansion(raw_words[route_word_index]):
        return None
    routes = _surface_routes_in_value(words[route_word_index])
    if not routes:
        return None
    literal_metadata = {
        field: words[word_index]
        for field, word_index in metadata_fields
        if not _has_shell_expansion(raw_words[word_index])
    }
    return sorted(routes)[0], literal_metadata


def unregistered_metadata_in_source(
    relative_path_text: str,
    source: str,
    manifest_rows: list[dict[str, str]],
) -> list[str]:
    """Flag public-surface registrations in one runtime reader that bypass the TSV.

    Detection is name-independent: a manifest-absent surface route is caught
    whether it is bound to a ``PUBLIC_SURFACE_*`` name, a natural name such as
    ``DONOR_URL``, or written inline as a bare literal URL. Only the surface's
    identity (its route or ``surface_id``) is used, so health, deploy-drift, and
    version routes owned outside the manifest are not treated as registrations.
    """
    allowed = _allowed_manifest_values(manifest_rows)
    rows_by_path = {row["path"]: row for row in manifest_rows}
    violations: list[str] = []
    assignments: list[tuple[int, str, str, str]] = []
    prefixes_with_unregistered_routes: set[str] = set()
    registered_routes_by_prefix: dict[str, set[str]] = {}
    source_lines = source.splitlines()
    direct_call_statements: dict[int, str] = {}
    line_index = 0
    while line_index < len(source_lines):
        line = source_lines[line_index]
        if re.match(r"^\s*(?:probe_url|probe_public_page)(?:\s|$)", line) is None:
            line_index += 1
            continue
        start_line_number = line_index + 1
        statement_parts: list[str] = []
        quote: str | None = None
        while True:
            line = source_lines[line_index]
            escaped = False
            for character_index, character in enumerate(line):
                if escaped:
                    escaped = False
                    continue
                if character == "\\" and quote != "'":
                    escaped = True
                    continue
                if character == "'" and quote != '"':
                    quote = None if quote == "'" else "'"
                    continue
                if character == '"' and quote != "'":
                    quote = None if quote == '"' else '"'
                    continue
                if character == "#" and quote is None and (character_index == 0 or line[character_index - 1].isspace()):
                    escaped = False
                    break
            continued = escaped and line.endswith("\\")
            statement_parts.append(line[:-1] if continued else line)
            if not continued or line_index + 1 >= len(source_lines):
                break
            line_index += 1
        direct_call_statements[start_line_number] = " ".join(part.strip() for part in statement_parts)
        line_index += 1

    for line_number, line in enumerate(source_lines, start=1):
        for match in _QUOTED_SURFACE_ID.finditer(line):
            value = match.group("value")
            if value not in allowed["surface_id"]:
                violations.append(f"{relative_path_text}:{line_number} unregistered surface_id={value}")

        for route in _surface_routes_in_value(line):
            if not _is_unregistered_surface_route(route, allowed):
                continue
            violations.append(f"{relative_path_text}:{line_number} unregistered surface_url={route}")

        direct_call_metadata = _direct_probe_call_metadata(direct_call_statements.get(line_number, line))
        if direct_call_metadata is not None:
            route, field_values = direct_call_metadata
            if route in rows_by_path:
                for field, value in field_values.items():
                    expected_value = rows_by_path[route][field]
                    if value != expected_value:
                        violations.append(
                            _registration_mismatch_message(
                                relative_path_text, line_number, route, field, value, expected_value
                            )
                        )

        assignment = _metadata_assignment(line)
        if assignment is None:
            continue
        prefix, field, raw_value = assignment
        assignments.append((line_number, prefix, field, raw_value))
        if field not in {"path", "url"}:
            continue
        for route in _surface_routes_in_value(raw_value):
            if _is_unregistered_surface_route(route, allowed):
                prefixes_with_unregistered_routes.add(prefix)
                violations.append(_unregistered_route_assignment_message(relative_path_text, line_number, field, route))
            elif route in rows_by_path:
                registered_routes_by_prefix.setdefault(prefix, set()).add(route)

    for line_number, prefix, field, raw_value in assignments:
        if prefix not in prefixes_with_unregistered_routes or field in {"path", "url"}:
            continue
        value = _display_assignment_value(raw_value)
        if value is None:
            continue
        if value not in allowed[field]:
            violations.append(f"{relative_path_text}:{line_number} unregistered {field}={value}")
    for line_number, prefix, field, raw_value in assignments:
        if prefix not in registered_routes_by_prefix or field in {"path", "url"}:
            continue
        value = _display_assignment_value(raw_value)
        if value is None:
            continue
        for route in sorted(registered_routes_by_prefix[prefix]):
            expected_value = rows_by_path[route][field]
            if value != expected_value:
                violations.append(
                    _registration_mismatch_message(relative_path_text, line_number, route, field, value, expected_value)
                )
    return violations


def _allowed_manifest_values(rows: list[dict[str, str]] | None = None) -> dict[str, set[str]]:
    if rows is None:
        rows = read_public_surface_manifest()
    return {field: {row[field] for row in rows} for field in MANIFEST_HEADER}


def scan_runtime_reader_source(relative_path_text: str, source: str) -> list[str]:
    """Scan one runtime reader's text against the committed TSV for registration bypasses."""
    return unregistered_metadata_in_source(relative_path_text, source, read_public_surface_manifest())


def unregistered_public_surface_metadata() -> list[str]:
    """Find literal surface registrations in runtime readers that bypass the TSV."""
    manifest_rows = read_public_surface_manifest()
    violations: list[str] = []
    for relative_path_text in sorted(EXPECTED_PRODUCTION_MANIFEST_READERS):
        source = (REPO_ROOT / relative_path_text).read_text(encoding="utf-8")
        violations.extend(unregistered_metadata_in_source(relative_path_text, source, manifest_rows))
    return violations


def assert_interpolated_metadata_detection() -> None:
    """Pin interpolated route and companion metadata bypass detection."""
    natural = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        "\n".join(
            (
                'DONOR_URL="${PROBE_BASE_URL%/}/donors?q=evil&by=name"',
                'DONOR_MARKER="data-testid=\\"evil-donor-row\\""',
                'DONOR_OWNER="legacy donor incident owner"',
            )
        ),
    )
    inline = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_url "donor" "${PROBE_BASE_URL%/}/donors?q=evil&by=name" "evil marker"',
    )
    inline_mid_word_hash_metadata = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith&by=name" wrong#${MARKER} "fatal" "donor_search_surface" '
        '"web donor search route"',
    )
    exempt = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'curl "${PROBE_BASE_URL%/}/api/health/version"\n'
        'curl "${PROBE_BASE_URL%/}/version.json"\n'
        'warm_up_public_page "${path}"',
    )

    assert any("surface_url=/donors?q=evil&by=name" in violation for violation in natural)
    assert any('marker=data-testid=\\"evil-donor-row\\"' in violation for violation in natural)
    assert any("owners=legacy donor incident owner" in violation for violation in natural)
    assert any("surface_url=/donors?q=evil&by=name" in violation for violation in inline)
    assert inline_mid_word_hash_metadata == []
    assert exempt == []


def assert_split_path_metadata_detection() -> None:
    """Pin relative path assignments used through a split base URL construction."""
    violations = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        "\n".join(
            (
                'DONOR_PATH="/manifest-absent"',
                'probe_url "donor" "${PROBE_BASE_URL%/}${DONOR_PATH}" "manifest absent marker"',
            )
        ),
    )

    assert any("path=/manifest-absent" in violation for violation in violations)
    assert any(".github/workflows/uptime_probe.yml" in violation for violation in violations)


def assert_manifest_row_metadata_detection() -> None:
    """Pin row-correlated metadata validation for hard-coded surface registrations."""
    registered_override = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        "\n".join(
            (
                'DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
                'DONOR_SURFACE_ID="donor_search_surface"',
                'DONOR_MARKER="wrong donor marker"',
                'DONOR_OWNERS="wrong donor owner"',
            )
        ),
    )
    cross_row_mix = scan_runtime_reader_source(
        ".github/workflows/uptime_probe.yml",
        "\n".join(
            (
                'DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
                'DONOR_SURFACE_ID="congress_surface"',
                'DONOR_KIND="person_sitemap"',
                'DONOR_PARITY_MODE="known_red"',
                'DONOR_UPTIME_MODE="skip"',
            )
        ),
    )

    assert any("marker=wrong donor marker" in violation for violation in registered_override)
    assert any("owners=wrong donor owner" in violation for violation in registered_override)
    assert any("surface_id=congress_surface" in violation for violation in cross_row_mix)
    assert any("kind=person_sitemap" in violation for violation in cross_row_mix)
    assert any("parity_mode=known_red" in violation for violation in cross_row_mix)


def assert_direct_call_metadata_detection() -> None:
    """Pin row-correlated metadata validation for direct literal probe calls."""
    probe_url_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_url "congress_surface" "https://civibus.shareborough.com/donors?q=smith&by=name" '
        "'data-testid=\"donor-result-row\"'",
    )
    public_page_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith&by=name" "wrong donor marker" "fatal" "donor_search_surface" "tests"',
    )
    single_quoted_dollar_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        "probe_public_page '/donors?q=smith&by=name' 'wrong $marker' 'fatal' "
        "'donor_search_surface' 'web donor search route'",
    )
    expanded_marker = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith&by=name" "$MARKER" "fatal" "donor_search_surface" "web donor search route"',
    )
    mixed_probe_url_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_url "congress_surface" "https://civibus.shareborough.com/donors?q=smith&by=name" "$MARKER"',
    )
    mixed_public_page_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith&by=name" "wrong donor marker" "fatal" "donor_search_surface" "$OWNERS"',
    )
    concatenated_route_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith"\'&by=name\' "wrong donor marker" "fatal" '
        '"donor_search_surface" "web donor search route"',
    )
    escaped_marker_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page "/donors?q=smith&by=name" wrong\\ donor\\ marker "fatal" '
        '"donor_search_surface" "web donor search route"',
    )
    tab_separated_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'probe_public_page\t"/donors?q=smith&by=name"\t"wrong donor marker"\t"fatal"\t'
        '"donor_search_surface"\t"web donor search route"',
    )
    continued_call_override = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        "\n".join(
            (
                "probe_public_page \\",
                '  "/donors?q=smith&by=name" \\',
                '  "wrong donor marker" \\',
                '  "fatal" \\',
                '  "donor_search_surface" \\',
                '  "web donor search route"',
            )
        ),
    )

    assert any(
        "metadata_mismatch" in violation
        and "route=/donors?q=smith&by=name" in violation
        and "surface_id=congress_surface expected=donor_search_surface" in violation
        for violation in probe_url_override
    ), f"direct probe_url surface_id override not detected: {probe_url_override}"
    assert any(
        "metadata_mismatch" in violation
        and "route=/donors?q=smith&by=name" in violation
        and 'marker=wrong donor marker expected=data-testid="donor-result-row"' in violation
        for violation in public_page_override
    ), f"direct probe_public_page marker override not detected: {public_page_override}"
    assert any(
        "metadata_mismatch" in violation
        and "route=/donors?q=smith&by=name" in violation
        and 'marker=wrong $marker expected=data-testid="donor-result-row"' in violation
        for violation in single_quoted_dollar_override
    ), f"single-quoted dollar marker override not detected: {single_quoted_dollar_override}"
    assert expanded_marker == []
    assert any(
        "surface_id=congress_surface expected=donor_search_surface" in violation
        for violation in mixed_probe_url_override
    )
    assert any("marker=wrong donor marker" in violation for violation in mixed_public_page_override)
    assert any("marker=wrong donor marker" in violation for violation in concatenated_route_override)
    assert any("marker=wrong donor marker" in violation for violation in escaped_marker_override)
    assert any("marker=wrong donor marker" in violation for violation in tab_separated_override)
    assert any("marker=wrong donor marker" in violation for violation in continued_call_override)


def assert_qualified_assignment_metadata_detection() -> None:
    """Pin metadata detection through shell qualifiers and YAML sequence dashes.

    A bare ``DONOR_MARKER=`` is caught, so a bypass only has to write the same
    registration as ``readonly``/``export``/``local``/``declare`` or as a YAML
    list item to keep the surface route registered while overriding the
    manifest's marker or owners.
    """
    qualified_specimens = {
        "readonly": (
            'readonly DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
            'readonly DONOR_MARKER="wrong donor marker"',
        ),
        "export": (
            'export DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
            'export DONOR_OWNERS="wrong donor owner"',
        ),
        "local": (
            '  local DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
            '  local DONOR_MARKER="wrong donor marker"',
        ),
        "declare": (
            'declare -r DONOR_URL="https://civibus.shareborough.com/donors?q=smith&by=name"',
            'declare -r DONOR_KIND="person_sitemap"',
        ),
        "yaml_sequence": (
            '- DONOR_URL: "https://civibus.shareborough.com/donors?q=smith&by=name"',
            '- DONOR_PARITY_MODE: "known_red"',
        ),
    }
    expected_overrides = {
        "readonly": "marker=wrong donor marker",
        "export": "owners=wrong donor owner",
        "local": "marker=wrong donor marker",
        "declare": "kind=person_sitemap",
        "yaml_sequence": "parity_mode=known_red",
    }
    for qualifier, lines in qualified_specimens.items():
        violations = scan_runtime_reader_source(".github/workflows/uptime_probe.yml", "\n".join(lines))
        override = expected_overrides[qualifier]
        assert any(
            "metadata_mismatch" in violation and "route=/donors?q=smith&by=name" in violation and override in violation
            for violation in violations
        ), f"{qualifier} override not detected: {violations}"

    unregistered_qualified = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'readonly DONOR_PATH="/manifest-absent"',
    )
    assert any("unregistered path=/manifest-absent" in violation for violation in unregistered_qualified)

    exempt_qualified = scan_runtime_reader_source(
        "infra/scripts/probe_deployed_surface_parity.sh",
        'readonly HEALTH_URL="${PROBE_BASE_URL%/}/api/health/content"\n'
        'export MANIFEST_PATH="infra/public_surface_probes.tsv"',
    )
    assert exempt_qualified == []


def assert_root_doc_source_filter() -> None:
    """Root docs are not production readers, but extensionless runtime owners are."""
    root_docs = (
        Path("README.md"),
        Path("PROJECT_OVERVIEW.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("CODE_MAP.md"),
        Path("DIRMAP.md"),
    )
    runtime_owners = (Path("Makefile"), Path("infra/Caddyfile"), Path("infra/api/Dockerfile"))
    assert {path.as_posix(): _is_production_source_path(path) for path in root_docs} == {
        "README.md": False,
        "PROJECT_OVERVIEW.md": False,
        "AGENTS.md": False,
        "CLAUDE.md": False,
        "CODE_MAP.md": False,
        "DIRMAP.md": False,
    }
    assert all(_is_production_source_path(path) for path in runtime_owners)


def release_targets() -> dict[str, object]:
    return json.loads(RELEASE_TARGETS_PATH.read_text(encoding="utf-8"))


def fixture_body_slug(path: str) -> str:
    return path.encode("utf-8").hex()


def helper_export_rows(*, denominator: int = 540, fec_rows: int = 540) -> list[dict[str, object]]:
    targets = release_targets()
    rows = []
    for index in range(denominator):
        has_fec_money = index < fec_rows
        rows.append(
            {
                "person_id": (
                    str(targets["finance_visual_person_id"]) if index == 0 else f"00000000-0000-4000-8000-{index:012d}"
                ),
                "person_name": (str(targets["finance_visual_person_name"]) if index == 0 else f"Member {index}"),
                "has_fec_money": has_fec_money,
                "candidate_id": f"10000000-0000-4000-8000-{index:012d}" if has_fec_money else None,
                "total_raised": (str(targets["finance_visual_minimum_total_raised"]) if index == 0 else "100.00"),
                "total_spent": "50.00",
                "net": "50.00",
                "cash_on_hand": "25.00",
                "summary_source": "fec_candidate_summary" if has_fec_money else None,
                "ie_support_total": "2424806.88" if index == 0 else "0.00",
                "ie_oppose_total": "8.00" if index == 0 else "0.00",
                "ie_support_count": 1 if index == 0 else 0,
                "ie_oppose_count": 1 if index == 0 else 0,
                "sources": [{"record_url": "https://www.fec.gov/data/candidate/example/"}],
            }
        )
    return rows


def expected_money_value_pass_lines() -> tuple[str, ...]:
    donor_query = release_targets()["finance_visual_donor_query"]
    return (
        "money_value_assertion candidates_http PASS numerator=200 denominator=200 "
        "diagnostic=/candidates returned HTTP 200",
        "money_value_assertion committees_rows PASS numerator=1 denominator=1 "
        "diagnostic=/committees rendered 1 result rows",
        "money_value_assertion donor_search_rows PASS numerator=1 denominator=1 "
        f"diagnostic=/donors?q={donor_query}&by=name rendered 1 result rows",
    )


def write_fixture(
    fixture_dir: Path,
    *,
    repo_paths: set[str],
    deployed_paths: set[str],
    sitemap_latency_seconds: str = "30.000",
    page_statuses: dict[str, int | str] | None = None,
    page_bodies: dict[str, str] | None = None,
    openapi_status: int = 200,
    api_version_payload: dict[str, str] | None = None,
    web_version_payload: dict[str, str] | None = None,
    api_version_status: int = 200,
    web_version_status: int = 200,
    helper_export_payload: object | None = None,
    helper_statuses: dict[str, int] | None = None,
    helper_donor_body: str | None = None,
) -> None:
    fixture_dir.mkdir()
    (fixture_dir / "repo_openapi_paths.json").write_text(json.dumps(sorted(repo_paths)), encoding="utf-8")
    (fixture_dir / "deployed_openapi.json").write_text(
        json.dumps({"paths": {path: {} for path in sorted(deployed_paths)}}),
        encoding="utf-8",
    )
    (fixture_dir / "deployed_openapi_status.txt").write_text(f"{openapi_status}\n", encoding="utf-8")
    statuses = page_statuses or {path: 200 for path in DEFAULT_PAGE_BODIES}
    (fixture_dir / "page_statuses.tsv").write_text(
        "".join(f"{path}\t{status}\n" for path, status in statuses.items()),
        encoding="utf-8",
    )
    (fixture_dir / "page_latencies.tsv").write_text(
        f"/sitemap.xml\t{sitemap_latency_seconds}\n",
        encoding="utf-8",
    )
    bodies = DEFAULT_PAGE_BODIES | (page_bodies or {})
    body_dir = fixture_dir / "page_bodies"
    body_dir.mkdir()
    for path in statuses:
        body = bodies.get(path, f"<html><body>{path}</body></html>")
        (body_dir / f"{fixture_body_slug(path)}.html").write_text(body, encoding="utf-8")
    (fixture_dir / "api_health_version.json").write_text(
        json.dumps(api_version_payload or {"git_sha": EXPECTED_SHA, "built_at": "2026-07-14T21:20:44Z"}),
        encoding="utf-8",
    )
    (fixture_dir / "web_version.json").write_text(
        json.dumps(web_version_payload or {"git_sha": EXPECTED_SHA, "built_at": "2026-07-14T21:20:44Z"}),
        encoding="utf-8",
    )
    (fixture_dir / "api_health_version_status.txt").write_text(f"{api_version_status}\n", encoding="utf-8")
    (fixture_dir / "web_version_status.txt").write_text(f"{web_version_status}\n", encoding="utf-8")
    write_helper_http_fixture(
        fixture_dir,
        helper_export_payload=helper_export_payload,
        helper_statuses=helper_statuses,
        helper_donor_body=helper_donor_body,
    )


def write_helper_http_fixture(
    fixture_dir: Path,
    *,
    helper_export_payload: object | None,
    helper_statuses: dict[str, int] | None,
    helper_donor_body: str | None = None,
) -> None:
    targets = release_targets()
    donor_query = targets["finance_visual_donor_query"]
    route_bodies = {
        "/api/public/v1/federal/export.json": json.dumps(
            helper_export_rows() if helper_export_payload is None else helper_export_payload
        ),
        "/candidates": '<li data-testid="candidate-result-row">Candidate</li>',
        "/committees": '<li data-testid="committee-result-row">Committee</li>',
        f"/donors?q={donor_query}&by=name": (
            helper_donor_body
            if helper_donor_body is not None
            else '<tr data-testid="donor-result-row"><td>Williams</td></tr>'
        ),
    }
    body_dir = fixture_dir / "helper_http_bodies"
    body_dir.mkdir()
    for route, body in route_bodies.items():
        (body_dir / f"{fixture_body_slug(route)}.txt").write_text(body, encoding="utf-8")
    (fixture_dir / "helper_http_statuses.tsv").write_text(
        "".join(f"{route}\t{status}\n" for route, status in (helper_statuses or {}).items()),
        encoding="utf-8",
    )


def manifest_row(
    *,
    surface_id: str = "sentinel_surface",
    kind: str = "static",
    path: str = "/manifest-sentinel",
    marker: str = "manifest sentinel marker",
    parity_mode: str = "fatal",
    uptime_mode: str = "skip",
    owners: str = "test owners",
) -> tuple[str, ...]:
    return (surface_id, kind, path, marker, parity_mode, uptime_mode, owners)


def person_surface_row(parity_mode: str) -> tuple[str, ...]:
    return manifest_row(
        surface_id="person_detail_surface",
        kind="person_sitemap",
        path=PERSON_SURFACE_SITEMAP_PATH,
        marker=PERSON_SURFACE_MARKER,
        parity_mode=parity_mode,
        uptime_mode="fatal",
    )


def person_surface_statuses(status: int = 200) -> dict[str, int]:
    return {path: 200 for path in DEFAULT_PAGE_BODIES} | {PERSON_SURFACE_PATH: status}


def write_manifest(
    manifest_path: Path,
    rows: tuple[tuple[str, ...], ...],
    *,
    header: tuple[str, ...] = MANIFEST_HEADER,
) -> None:
    manifest_path.write_text(
        "\n".join("\t".join(fields) for fields in (header, *rows)) + "\n",
        encoding="utf-8",
    )


def write_temp_manifest_probe(
    temp_repo: Path,
    rows: tuple[tuple[str, ...], ...],
    *,
    header: tuple[str, ...] = MANIFEST_HEADER,
) -> Path:
    scripts_dir = temp_repo / "infra/scripts"
    scripts_dir.mkdir(parents=True)
    copied_probe_path = scripts_dir / PROBE_PATH.name
    shutil.copyfile(PROBE_PATH, copied_probe_path)
    write_manifest(temp_repo / "infra/public_surface_probes.tsv", rows, header=header)
    return copied_probe_path


def write_static_manifest_probe(
    temp_repo: Path,
    *,
    path: str,
    marker: str = "manifest sentinel marker",
    parity_mode: str = "fatal",
) -> Path:
    return write_temp_manifest_probe(
        temp_repo,
        (manifest_row(path=path, marker=marker, parity_mode=parity_mode),),
    )


def run_probe(
    fixture_dir: Path,
    *,
    expected_sha: str = EXPECTED_SHA,
    extra_env: dict[str, str] | None = None,
    probe_path: Path = PROBE_PATH,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CIVIBUS_PUBLIC_BASE_URL", None)
    env.pop("CIVIBUS_PERSON_SURFACE_MEMBERSHIP", None)
    env["CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR"] = str(fixture_dir)
    env["CIVIBUS_EXPECTED_SHA"] = expected_sha
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(probe_path)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
