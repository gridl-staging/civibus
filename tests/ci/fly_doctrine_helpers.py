"""Semantic helpers for the current-production-locality doctrine contract.

Extracted 2026-08-23 from ``test_fly_ops_docs_contract.py`` so the single Fly
operations documentation contract owner stays under the 800-line review limit.
This module holds ONLY the reusable doctrine parsers — markdown section
classification, clause scoping, and the affirmative/prohibition matchers. Every
contract assertion stays in the test owner; there is no second documentation
contract here.
"""

from __future__ import annotations

from pathlib import Path
import re


FLY_LOCALITY_FACTS = (
    "civibus-db",
    "civibus-api",
    "civibus-web",
    "civibus-caddy",
    "civibus-refresh",
    "civibus-db.internal:5432",
    "https://civibus.shareborough.com",
)
# A date alone never marks a section historical; only explicit status framing does.
HISTORICAL_HEADING_MARKERS = ("historical", "parked", "superseded", "retired", "postmortem")
APR30_MARKERS = ("apr 30", "2026-04-30")
BARE_DOCKER_MARKERS = ("bare-docker", "bare docker", "bare `docker", "bare form", "docker compose up")
CURRENT_PROD_OPS_FORBIDDEN = ("5.78.207.136", "Hetzner", "prod_compose.sh", *BARE_DOCKER_MARKERS)

_FUTURE = r"future|target|planned|eventual|will|intend|going to|plans? to|should be"
# Non-current Fly language is matched per clause, so an affirmative Fly sentence
# stays valid when a later clause prohibits the retired path.
_NON_CURRENT_FLY_RE = re.compile(
    r"\bFly\b[^.\n]{0,100}\b(?:isn['’]t|is not|not|never|no longer|future|target|planned|eventual|will)\b"
    r"|\b(?:not|never|no longer|future|planned|eventual|will|do not|don['’]t)\b[^.\n]{0,100}\bFly\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_FLY_RE = re.compile(
    r"\b(?:current|active)\b[^.\n]{0,100}\b(?:production|read-only|refresh)\b[^.\n]{0,100}"
    r"\b(?:is|runs on|uses|points to|routes to|through|via)\b[^.\n]{0,60}\bFly\b"
    r"|\bFly\b[^.\n]{0,100}\b(?:is|serves as|remains|runs|provides|hosts)\b[^.\n]{0,100}"
    r"\b(?:current|active)\b[^.\n]{0,100}\b(?:production|read-only|refresh|locality|path|route|access)\b",
    re.IGNORECASE,
)
_LEGACY_PROHIBITION_PREFIX = (
    r"(?:do not|don['’]t|never|avoid|must not|cannot|stop using|instead of|rather than"
    r"|deprecated|retired|superseded|parked|historical)"
)
_LEGACY_PROHIBITION_SUFFIX = (
    r"(?:(?:is|are|was|were|remains?|stays?)\s+)?"
    r"(?:no longer|forbidden|prohibited|banned|deprecated|retired|superseded|parked|historical|a failure mode)"
)
_STATUS_MARKERS = "|".join(HISTORICAL_HEADING_MARKERS)
_NEGATED_HISTORICAL_HEADING_RE = re.compile(
    rf"\b(?:not|never|no longer)\b[^\n]{{0,40}}\b(?:{_STATUS_MARKERS})\b",
    re.IGNORECASE,
)
_CURRENT_HISTORICAL_HEADING_RE = re.compile(
    rf"^##\s+(?:current|active)\b"
    rf"|\b(?:{_STATUS_MARKERS})\b[^\n]{{0,30}}\b(?:but|however|yet)\b[^\n]{{0,30}}\b(?:current|active|reactivated)\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_STATUS_RE = re.compile(
    rf"\b(?:is|was|are|were|remains?|stays?|has been|have been)\b[^.\n]{{0,60}}\b(?:{_STATUS_MARKERS})\b",
    re.IGNORECASE,
)
_NON_AFFIRMATIVE_STATUS_RE = re.compile(
    rf"\b(?:isn['’]t|is not|are not|aren['’]t|not|never|no longer|{_FUTURE})\b[^.\n]{{0,60}}\b(?:{_STATUS_MARKERS})\b",
    re.IGNORECASE,
)
_CURRENT_STATUS_RE = re.compile(
    r"\b(?:is|are|becomes?|became|has become|have become|will\s+(?:now\s+)?be)\s+(?:now\s+)?"
    r"(?:active|current|live|the\s+(?:current\s+)?production(?:\s+(?:path|stack|locality))?)"
    r"(?:\s+again)?\b|\breactivated\b",
    re.IGNORECASE,
)
# Split on sentence/clause boundaries only where a period ends a sentence, so
# `prod_compose.sh` and `5.78.207.136` survive intact inside a single clause.
_CLAUSE_SPLIT_RE = re.compile(r"\.\s+|\.$|[;\n]|\s+—\s+")


def relpath(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root))


def doc_lede(text: str) -> str:
    return re.split(r"(?m)^## .+$", text, maxsplit=1)[0]


def heading_is_historical(heading: str) -> bool:
    low = heading.lower()
    status_is_reactivated = re.search(
        rf"\b(?:{_STATUS_MARKERS})\b[^\n]{{0,50}}\b(?:now|again)\b[^\n]{{0,20}}"
        r"(?:\b(?:active|current|live)\b|\bproduction\s+(?:path|stack|locality)\b)",
        heading,
        re.IGNORECASE,
    )
    return (
        any(marker in low for marker in HISTORICAL_HEADING_MARKERS)
        and not _NEGATED_HISTORICAL_HEADING_RE.search(heading)
        and not _CURRENT_HISTORICAL_HEADING_RE.search(heading)
        and not status_is_reactivated
    )


def markdown_sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(## .+)$", text)
    return [("", parts[0])] + [
        (parts[index], parts[index + 1] if index + 1 < len(parts) else "") for index in range(1, len(parts), 2)
    ]


def current_doctrine_text(text: str) -> str:
    return "\n".join(head + body for head, body in markdown_sections(text) if not heading_is_historical(head))


def historical_doctrine_sections(text: str) -> list[str]:
    return [head + body for head, body in markdown_sections(text) if head and heading_is_historical(head)]


def claim_units(text: str) -> list[str]:
    return [" ".join(unit.split()) for unit in re.split(r"(?m)\n\s*\n|^\s*-\s+", text) if unit.strip()]


def clauses(text: str) -> list[str]:
    return [clause.strip() for unit in claim_units(text) for clause in _CLAUSE_SPLIT_RE.split(unit) if clause.strip()]


def has_affirmative_fly_claim(text: str, required_terms: tuple[str, ...]) -> bool:
    """True when one clause affirms Fly as the current locality for every required term."""
    return any(
        all(term.lower() in clause.lower() for term in required_terms)
        and _AFFIRMATIVE_FLY_RE.search(clause)
        and not _NON_CURRENT_FLY_RE.search(clause)
        for clause in clauses(text)
    )


def lede_is_parked(lede: str) -> bool:
    """True only for an affirmative historical/parked status claim, not marker presence."""
    lede_clauses = clauses(lede)
    if any(_clause_reactivates_legacy_stack(clause) for clause in lede_clauses):
        return False
    return any(
        _AFFIRMATIVE_STATUS_RE.search(clause) and not _NON_AFFIRMATIVE_STATUS_RE.search(clause)
        for clause in lede_clauses
    )


def _clause_reactivates_legacy_stack(clause: str) -> bool:
    reactivation_patterns = (
        _CURRENT_STATUS_RE,
        re.compile(
            r"\b(?:is|are|was|were|remains?)\s+(?:not|no longer)\s+"
            r"(?:parked|historical|retired|superseded|prohibited|forbidden|deprecated|banned)\b"
            r"|\b(?:now\s+)?(?:runs?|serves?|operates?)\b[^.\n]{0,40}\bproduction\b",
            re.IGNORECASE,
        ),
    )
    for pattern in reactivation_patterns:
        for match in pattern.finditer(clause):
            fly_is_subject = re.search(
                r"\bFly(?:\s+(?:stack|path|locality|route|access|production))?\s*$",
                clause[: match.start()],
                re.IGNORECASE,
            )
            if fly_is_subject:
                continue
            return True
    return False


def has_historical_apr30_hetzner_bare_docker_rationale(text: str) -> bool:
    """True when an explicitly historical section still carries the Apr-30 rationale."""
    return any(
        "hetzner" in lowered
        and any(marker in lowered for marker in APR30_MARKERS)
        and "prod_compose.sh" in lowered
        and any(marker in lowered for marker in BARE_DOCKER_MARKERS)
        for section in historical_doctrine_sections(text)
        for lowered in (section.lower(),)
    )


def current_prod_ops_forbidden_fragments(text: str) -> list[tuple[str, str]]:
    """Legacy production-path fragments stated as active directives, with their clause.

    A clause that prohibits or parks the path is skipped, so compliant doctrine
    such as "Do not use Hetzner or prod_compose.sh for production proof" is not
    reported as a current production instruction.
    """
    found: dict[str, str] = {}
    for clause in clauses(text):
        lowered = clause.lower()
        for fragment in CURRENT_PROD_OPS_FORBIDDEN:
            if fragment.lower() in lowered and not _legacy_fragment_is_prohibited(clause, fragment):
                found.setdefault(fragment, clause)
    return list(found.items())


def _legacy_fragment_is_prohibited(clause: str, fragment: str) -> bool:
    """Return whether prohibition/status language specifically governs ``fragment``."""
    escaped_fragment = re.escape(fragment)
    prefix = re.compile(
        rf"\b{_LEGACY_PROHIBITION_PREFIX}\b(?P<context>[^;\n]{{0,100}}){escaped_fragment}",
        re.IGNORECASE,
    )
    active_pivot = re.compile(r"(?:,\s*|\b(?:and|but)\s+)(?:use|run|route|deploy|operate)\b", re.IGNORECASE)
    if any(not active_pivot.search(match.group("context")) for match in prefix.finditer(clause)):
        return True

    suffix = re.compile(
        rf"{escaped_fragment}(?P<context>[^;\n]{{0,100}})\b{_LEGACY_PROHIBITION_SUFFIX}\b",
        re.IGNORECASE,
    )
    return any(
        not _clause_reactivates_legacy_stack(clause[match.start() :])
        and not re.search(r"\bFly\b", match.group("context"), re.IGNORECASE)
        for match in suffix.finditer(clause)
    )
