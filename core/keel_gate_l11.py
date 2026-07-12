
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from jsonschema.validators import validator_for
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]

L11_SCOPE = "web_editorial_copy"
L11_OWNER_FILES = (
    "web/src/lib/config/app.ts",
    "web/src/lib/campaign-finance-detail/presentation.ts",
    "web/src/lib/civic-detail/presentation.ts",
    "web/src/routes/+page.svelte",
    "web/src/lib/detail-trust/presentation.ts",
)


class L11EditorialRow(BaseModel, extra="forbid"):
    copy_id: str = Field(min_length=1)
    owner_file: str = Field(min_length=1)
    text: str = Field(min_length=1)


class L11EditorialCollection(BaseModel, extra="forbid"):
    scope: str
    owner_files: list[str]
    rows: list[L11EditorialRow]


class L11Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    owner_files: list[str]
    rows: list[L11EditorialRow]


@dataclass(frozen=True)
class _AppShellExtraction:
    """Container for APP_SHELL literals used to emit deterministic L11 rows."""

    home_object: str
    landing_object: str
    cta_object: str
    action_objects: list[str]
    methodology_object: str
    methodology_sections: list[str]
    methodology_confidence_labels: list[str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _repo_sha(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def _read_owner_file(*, repo_root: Path, owner_file: str) -> str:
    owner_path = repo_root / owner_file
    if not owner_path.is_file():
        raise ValueError(f"missing owner file: {owner_file}")
    return owner_path.read_text(encoding="utf-8")


def _extract_string_assignment(*, source_text: str, owner_file: str, symbol_name: str) -> str:
    pattern = re.compile(
        rf"(?:export\s+)?const\s+{re.escape(symbol_name)}\s*=\s*([\"'])(?P<value>(?:\\.|(?!\1).)*)\1\s*;",
        flags=re.DOTALL,
    )
    match = pattern.search(source_text)
    if match is None:
        raise ValueError(f"{symbol_name} is missing in {owner_file}")
    return match.group("value")


def _extract_object_literal(*, source_text: str, owner_file: str, symbol_name: str) -> str:
    symbol_anchor = f"export const {symbol_name} ="
    anchor_index = source_text.find(symbol_anchor)
    if anchor_index < 0:
        raise ValueError(f"{symbol_name} is missing in {owner_file}")

    object_start = source_text.find("{", anchor_index)
    if object_start < 0:
        raise ValueError(f"{symbol_name} object literal is missing in {owner_file}")

    depth = 0
    in_string: str | None = None
    escaped = False
    for index in range(object_start, len(source_text)):
        char = source_text[index]
        if in_string is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == in_string:
                in_string = None
            continue

        if char in ('"', "'", "`"):
            in_string = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return source_text[object_start : index + 1]

    raise ValueError(f"{symbol_name} object literal is unterminated in {owner_file}")


def _find_balanced_block(
    *, source_text: str, owner_file: str, start_index: int, open_char: str, close_char: str
) -> str:
    if start_index >= len(source_text) or source_text[start_index] != open_char:
        raise ValueError(f"expected {open_char!r} at index {start_index} in {owner_file}")

    depth = 0
    in_string: str | None = None
    escaped = False

    for index in range(start_index, len(source_text)):
        char = source_text[index]
        if in_string is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == in_string:
                in_string = None
            continue

        if char in ('"', "'", "`"):
            in_string = char
            continue
        if char == "\\":
            continue
        if char == open_char:
            depth += 1
            continue
        if char == close_char:
            depth -= 1
            if depth == 0:
                return source_text[start_index : index + 1]
    raise ValueError(f"unterminated {open_char}{close_char} block in {owner_file}")


def _extract_property_literal(
    *, source_text: str, owner_file: str, property_name: str, opening_char: str, closing_char: str
) -> str:
    key_pattern = re.compile(rf"{re.escape(property_name)}\s*:\s*")
    in_string: str | None = None
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(source_text):
        char = source_text[index]
        next_char = source_text[index + 1] if index + 1 < len(source_text) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in ('"', "'", "`"):
            in_string = char
            index += 1
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        previous_char = source_text[index - 1] if index > 0 else ""
        if previous_char.isalnum() or previous_char in "_$":
            index += 1
            continue

        key_match = key_pattern.match(source_text, index)
        if key_match is None:
            index += 1
            continue

        value_index = key_match.end()
        while value_index < len(source_text) and source_text[value_index].isspace():
            value_index += 1

        return _find_balanced_block(
            source_text=source_text,
            owner_file=owner_file,
            start_index=value_index,
            open_char=opening_char,
            close_char=closing_char,
        )

    raise ValueError(f"{property_name} is missing in {owner_file}")


def _extract_top_level_property_literal(
    *,
    source_text: str,
    owner_file: str,
    property_name: str,
    opening_char: str,
    closing_char: str,
) -> str:
    """Extract a property literal that is declared at object depth 1."""
    key_pattern = re.compile(rf"{re.escape(property_name)}\s*:\s*")

    depth = 0
    in_string: str | None = None
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(source_text):
        char = source_text[index]
        next_char = source_text[index + 1] if index + 1 < len(source_text) else ""
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in ('"', "'", "`"):
            in_string = char
            index += 1
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue

        if depth == 1:
            previous_char = source_text[index - 1] if index > 0 else ""
            key_match = None
            if not previous_char.isalnum() and previous_char not in "_$":
                key_match = key_pattern.match(source_text, index)
            if key_match is not None:
                value_index = key_match.end()
                while value_index < len(source_text) and source_text[value_index].isspace():
                    value_index += 1
                return _find_balanced_block(
                    source_text=source_text,
                    owner_file=owner_file,
                    start_index=value_index,
                    open_char=opening_char,
                    close_char=closing_char,
                )
        index += 1

    raise ValueError(f"top-level {property_name} is missing in {owner_file}")


def _extract_string_property(*, source_text: str, owner_file: str, property_name: str) -> str:
    pattern = re.compile(
        rf"\b{re.escape(property_name)}\s*:\s*([\"'])(?P<value>(?:\\.|(?!\1).)*)\1",
        flags=re.DOTALL,
    )
    match = pattern.search(source_text)
    if match is None:
        raise ValueError(f"{property_name} string property is missing in {owner_file}")
    return match.group("value").strip()


def _extract_action_objects(*, actions_array_text: str, owner_file: str) -> list[str]:
    action_objects: list[str] = []
    index = 0
    in_string: str | None = None
    escaped = False
    while index < len(actions_array_text):
        char = actions_array_text[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue
        if char in ('"', "'", "`"):
            in_string = char
            index += 1
            continue
        if char == "{":
            action_object = _find_balanced_block(
                source_text=actions_array_text,
                owner_file=owner_file,
                start_index=index,
                open_char="{",
                close_char="}",
            )
            action_objects.append(action_object)
            index += len(action_object)
            continue
        index += 1
    if not action_objects:
        raise ValueError(f"object array is empty in {owner_file}")
    return action_objects


def _append_landing_action_rows(
    *, app_shell_copy_rows: list[tuple[str, str]], action_objects: list[str], app_owner: str
) -> None:
    """Append deterministic landing action label/description rows."""
    for action_index, action_object in enumerate(action_objects, start=1):
        app_shell_copy_rows.append(
            (
                f"app-shell-landing-action-{action_index:03d}-label",
                _extract_string_property(source_text=action_object, owner_file=app_owner, property_name="label"),
            )
        )
        app_shell_copy_rows.append(
            (
                f"app-shell-landing-action-{action_index:03d}-description",
                _extract_string_property(source_text=action_object, owner_file=app_owner, property_name="description"),
            )
        )


def _append_methodology_rows(
    *,
    app_shell_copy_rows: list[tuple[str, str]],
    methodology_object: str,
    methodology_sections: list[str],
    methodology_confidence_labels: list[str],
    app_owner: str,
) -> None:
    """Append deterministic methodology heading, sections, and confidence rows."""
    app_shell_copy_rows.extend(
        [
            (
                "app-shell-methodology-heading",
                _extract_string_property(source_text=methodology_object, owner_file=app_owner, property_name="heading"),
            ),
            (
                "app-shell-methodology-coverage-summary",
                _extract_string_property(
                    source_text=methodology_object, owner_file=app_owner, property_name="coverageSummary"
                ),
            ),
        ]
    )
    for section_index, section_object in enumerate(methodology_sections, start=1):
        app_shell_copy_rows.append(
            (
                f"app-shell-methodology-section-{section_index:03d}-heading",
                _extract_string_property(source_text=section_object, owner_file=app_owner, property_name="heading"),
            )
        )
        app_shell_copy_rows.append(
            (
                f"app-shell-methodology-section-{section_index:03d}-body",
                _extract_string_property(source_text=section_object, owner_file=app_owner, property_name="body"),
            )
        )
    app_shell_copy_rows.append(
        (
            "app-shell-methodology-confidence-heading",
            _extract_string_property(
                source_text=methodology_object, owner_file=app_owner, property_name="confidenceHeading"
            ),
        )
    )
    for label_index, confidence_label_object in enumerate(methodology_confidence_labels, start=1):
        app_shell_copy_rows.append(
            (
                f"app-shell-methodology-confidence-label-{label_index:03d}-label",
                _extract_string_property(
                    source_text=confidence_label_object, owner_file=app_owner, property_name="label"
                ),
            )
        )
        app_shell_copy_rows.append(
            (
                f"app-shell-methodology-confidence-label-{label_index:03d}-description",
                _extract_string_property(
                    source_text=confidence_label_object,
                    owner_file=app_owner,
                    property_name="description",
                ),
            )
        )


def _extract_app_shell_literals(*, app_shell_object: str, app_owner: str) -> _AppShellExtraction:
    """Extract APP_SHELL literals and nested arrays needed for row emission."""
    home_object = _extract_property_literal(
        source_text=app_shell_object,
        owner_file=app_owner,
        property_name="home",
        opening_char="{",
        closing_char="}",
    )
    landing_object = _extract_property_literal(
        source_text=app_shell_object,
        owner_file=app_owner,
        property_name="landing",
        opening_char="{",
        closing_char="}",
    )
    cta_object = _extract_property_literal(
        source_text=landing_object,
        owner_file=app_owner,
        property_name="cta",
        opening_char="{",
        closing_char="}",
    )
    actions_array = _extract_property_literal(
        source_text=landing_object,
        owner_file=app_owner,
        property_name="actions",
        opening_char="[",
        closing_char="]",
    )
    methodology_object = _extract_top_level_property_literal(
        source_text=app_shell_object,
        owner_file=app_owner,
        property_name="methodology",
        opening_char="{",
        closing_char="}",
    )
    methodology_sections_array = _extract_property_literal(
        source_text=methodology_object,
        owner_file=app_owner,
        property_name="sections",
        opening_char="[",
        closing_char="]",
    )
    methodology_confidence_labels_array = _extract_property_literal(
        source_text=methodology_object,
        owner_file=app_owner,
        property_name="confidenceLabels",
        opening_char="[",
        closing_char="]",
    )
    return _AppShellExtraction(
        home_object=home_object,
        landing_object=landing_object,
        cta_object=cta_object,
        action_objects=_extract_action_objects(actions_array_text=actions_array, owner_file=app_owner),
        methodology_object=methodology_object,
        methodology_sections=_extract_action_objects(
            actions_array_text=methodology_sections_array, owner_file=app_owner
        ),
        methodology_confidence_labels=_extract_action_objects(
            actions_array_text=methodology_confidence_labels_array,
            owner_file=app_owner,
        ),
    )


def _build_static_and_landing_rows(*, extracted: _AppShellExtraction, app_owner: str) -> list[tuple[str, str]]:
    """Build deterministic APP_SHELL static and landing rows prior to append helpers."""
    return [
        (
            "app-shell-static-routes-home-title",
            _extract_string_property(source_text=extracted.home_object, owner_file=app_owner, property_name="title"),
        ),
        (
            "app-shell-static-routes-home-description",
            _extract_string_property(
                source_text=extracted.home_object, owner_file=app_owner, property_name="description"
            ),
        ),
        (
            "app-shell-landing-eyebrow",
            _extract_string_property(
                source_text=extracted.landing_object, owner_file=app_owner, property_name="eyebrow"
            ),
        ),
        (
            "app-shell-landing-heading",
            _extract_string_property(
                source_text=extracted.landing_object, owner_file=app_owner, property_name="heading"
            ),
        ),
        (
            "app-shell-landing-body",
            _extract_string_property(source_text=extracted.landing_object, owner_file=app_owner, property_name="body"),
        ),
        (
            "app-shell-landing-coverage-heading",
            _extract_string_property(
                source_text=extracted.landing_object, owner_file=app_owner, property_name="coverageHeading"
            ),
        ),
        (
            "app-shell-landing-coverage-summary",
            _extract_string_property(
                source_text=extracted.landing_object, owner_file=app_owner, property_name="coverageSummary"
            ),
        ),
        (
            "app-shell-landing-cta-label",
            _extract_string_property(source_text=extracted.cta_object, owner_file=app_owner, property_name="label"),
        ),
        (
            "app-shell-landing-cta-description",
            _extract_string_property(
                source_text=extracted.cta_object, owner_file=app_owner, property_name="description"
            ),
        ),
    ]


def _collect_app_shell_rows(*, repo_root: Path) -> list[L11EditorialRow]:
    """Collect app-shell static, landing, and methodology rows in deterministic order."""
    app_owner = L11_OWNER_FILES[0]
    app_shell_text = _read_owner_file(repo_root=repo_root, owner_file=app_owner)
    app_shell_object = _extract_object_literal(
        source_text=app_shell_text, owner_file=app_owner, symbol_name="APP_SHELL"
    )
    extracted = _extract_app_shell_literals(app_shell_object=app_shell_object, app_owner=app_owner)
    app_shell_copy_rows = _build_static_and_landing_rows(extracted=extracted, app_owner=app_owner)
    _append_landing_action_rows(
        app_shell_copy_rows=app_shell_copy_rows,
        action_objects=extracted.action_objects,
        app_owner=app_owner,
    )
    _append_methodology_rows(
        app_shell_copy_rows=app_shell_copy_rows,
        methodology_object=extracted.methodology_object,
        methodology_sections=extracted.methodology_sections,
        methodology_confidence_labels=extracted.methodology_confidence_labels,
        app_owner=app_owner,
    )
    return [
        L11EditorialRow(
            copy_id=copy_id,
            owner_file=app_owner,
            text=text,
        )
        for copy_id, text in app_shell_copy_rows
    ]


def _collect_non_app_shell_rows(*, repo_root: Path) -> list[L11EditorialRow]:
    """Collect remaining rows outside APP_SHELL in deterministic owner order."""
    rows: list[L11EditorialRow] = []
    outside_spending_owner = L11_OWNER_FILES[1]
    outside_spending_text = _read_owner_file(repo_root=repo_root, owner_file=outside_spending_owner)
    rows.append(
        L11EditorialRow(
            copy_id="outside-spending-unavailable",
            owner_file=outside_spending_owner,
            text=_extract_string_assignment(
                source_text=outside_spending_text,
                owner_file=outside_spending_owner,
                symbol_name="OUTSIDE_SPENDING_UNAVAILABLE_MESSAGE",
            ),
        )
    )

    contest_owner = L11_OWNER_FILES[2]
    contest_text = _read_owner_file(repo_root=repo_root, owner_file=contest_owner)
    trust_owner = L11_OWNER_FILES[4]
    trust_text = _read_owner_file(repo_root=repo_root, owner_file=trust_owner)
    rows.append(
        L11EditorialRow(
            copy_id="al-freshness-note",
            owner_file=trust_owner,
            text=_extract_string_assignment(
                source_text=trust_text,
                owner_file=trust_owner,
                symbol_name="AL_FRESHNESS_NOTE",
            ),
        )
    )
    rows.append(
        L11EditorialRow(
            copy_id="ga-freshness-note",
            owner_file=trust_owner,
            text=_extract_string_assignment(
                source_text=trust_text,
                owner_file=trust_owner,
                symbol_name="GA_FRESHNESS_NOTE",
            ),
        )
    )
    rows.append(
        L11EditorialRow(
            copy_id="contest-candidate-list-warning",
            owner_file=contest_owner,
            text=_extract_string_assignment(
                source_text=contest_text,
                owner_file=contest_owner,
                symbol_name="CONTEST_CANDIDATE_LIST_WARNING",
            ),
        )
    )

    landing_owner = L11_OWNER_FILES[3]
    landing_text = _read_owner_file(repo_root=repo_root, owner_file=landing_owner)
    if "<h3>Take action</h3>" not in landing_text:
        raise ValueError(f"Take action heading is missing in {landing_owner}")
    rows.append(
        L11EditorialRow(
            copy_id="landing-take-action-heading",
            owner_file=landing_owner,
            text="Take action",
        )
    )
    return rows


def collect_editorial_rows(*, repo_root: Path) -> L11EditorialCollection:
    """Collect deterministic L11 rows from explicit user-facing copy owners."""
    rows = [
        *_collect_app_shell_rows(repo_root=repo_root),
        *_collect_non_app_shell_rows(repo_root=repo_root),
    ]

    return L11EditorialCollection(
        scope=L11_SCOPE,
        owner_files=list(L11_OWNER_FILES),
        rows=rows,
    )


def _evidence_status(collection: L11EditorialCollection) -> str:
    owner_files_with_rows = {row.owner_file for row in collection.rows}
    return "pass" if owner_files_with_rows == set(collection.owner_files) else "fail"


def _validate_payload(*, payload: dict[str, object], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(f"schema-invalid L11 evidence payload: {errors[0].message}")


def write_l11_evidence(
    *,
    repo_root: Path,
    evidence_root: Path,
    evidence_date: date,
    produced_at: datetime,
    collection: L11EditorialCollection,
) -> Path:
    """Write schema-validated L11 evidence under evidence/L11/{scope}/{date}.json."""
    scope_root = evidence_root / collection.scope
    scope_root.mkdir(parents=True, exist_ok=True)

    payload = L11Evidence(
        layer="L11",
        scope=collection.scope,
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=_repo_sha(repo_root),
        gate_command="make gate-L11",
        status=_evidence_status(collection),
        owner_files=collection.owner_files,
        rows=collection.rows,
    )
    serialized_payload = payload.model_dump(mode="json")
    schema_path = repo_root / "evidence_schemas" / "L11.json"
    if not schema_path.is_file():
        raise ValueError(f"missing L11 schema: {schema_path}")
    _validate_payload(payload=serialized_payload, schema_path=schema_path)

    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(serialized_payload, indent=2) + "\n", encoding="utf-8")
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect deterministic L11 editorial-copy evidence")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to write evidence for (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--evidence-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the L11 collector and emit evidence for the configured date."""
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_date = _parse_date(args.date)
    produced_at = _utc_now()
    evidence_root = args.evidence_root.resolve() if args.evidence_root else repo_root / "evidence" / "L11"

    try:
        collection = collect_editorial_rows(repo_root=repo_root)
        evidence_path = write_l11_evidence(
            repo_root=repo_root,
            evidence_root=evidence_root,
            evidence_date=evidence_date,
            produced_at=produced_at,
            collection=collection,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L11 failed: {error}", file=sys.stderr)
        return 1

    status = _evidence_status(collection)
    print(
        f"{status.upper()}: scope={collection.scope} owner_files={len(collection.owner_files)} "
        f"rows={len(collection.rows)} evidence={evidence_path}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
