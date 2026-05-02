
from __future__ import annotations

import argparse
import fnmatch
from dataclasses import dataclass
from pathlib import Path

# Allowlist of repo-relative path patterns that may be committed by this transport.
# These match against POSIX-style relative paths.
_ALLOWED_PATTERNS: tuple[str, ...] = (
    "evidence/L*/**",
    "evidence/review/**",
    "findings/**",
)

# Redaction blocklist. Any filename matching one of these patterns is rejected even
# if its parent directory is allowlisted. Patterns operate on the file name only.
_REDACTION_BLOCKLIST: tuple[str, ...] = (
    "*secret*",
    "*credential*",
    ".env*",
    "*token*",
    "*password*",
)


@dataclass(slots=True)
class EnumerationResult:
    allowed: list[Path]
    rejected: list[Path]


def _matches_any(*, value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _is_publishable(*, repo_root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    relative_posix = relative.as_posix()
    if not _matches_any(value=relative_posix, patterns=_ALLOWED_PATTERNS):
        return False
    if _matches_any(value=candidate.name, patterns=_REDACTION_BLOCKLIST):
        return False
    return True


def enumerate_publishable(*, repo_root: Path, candidate_paths: list[Path]) -> EnumerationResult:
    """Split candidate paths into publishable (allowed) and rejected sets.

    Both sets are returned so callers can log/preview the rejected ones.
    """
    allowed: list[Path] = []
    rejected: list[Path] = []
    for candidate in candidate_paths:
        if _is_publishable(repo_root=repo_root, candidate=candidate):
            allowed.append(candidate)
        else:
            rejected.append(candidate)
    return EnumerationResult(allowed=allowed, rejected=rejected)


def discover_candidate_paths(*, repo_root: Path) -> list[Path]:
    """Walk the publish trees and return every file that is a candidate to commit."""
    candidates: list[Path] = []
    for tree_relative in ("evidence", "findings"):
        tree_root = repo_root / tree_relative
        if not tree_root.is_dir():
            continue
        for path in tree_root.rglob("*"):
            if path.is_file() and _is_publishable(repo_root=repo_root, candidate=path):
                candidates.append(path)
    return sorted(candidates, key=lambda p: p.relative_to(repo_root).as_posix())


def build_commit_message(*, repo_root: Path, paths: list[Path]) -> str:
    """Deterministic commit message for the publish set.

    Subject line summarizes the layer/tree mix; body lists every published path
    in repo-relative POSIX form, sorted.
    """
    relative_sorted = sorted(p.relative_to(repo_root).as_posix() for p in paths)
    layers: list[str] = []
    has_findings = False
    for path in relative_sorted:
        parts = path.split("/")
        if parts[0] == "evidence" and len(parts) >= 2:
            label = parts[1]
            if label not in layers:
                layers.append(label)
        elif parts[0] == "findings":
            has_findings = True
    summary_parts: list[str] = []
    if layers:
        summary_parts.append(" + ".join(sorted(layers)))
    if has_findings:
        summary_parts.append("findings")
    summary = " + ".join(summary_parts) if summary_parts else "no-op"
    subject = f"evidence/continuous: publish {summary} artifacts"
    body_lines = ["", "Paths:"] + [f"- {item}" for item in relative_sorted]
    return "\n".join([subject, *body_lines]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enumerate continuous-gate evidence artifacts safe to commit.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--print-paths", action="store_true", help="Print one publishable path per line.")
    parser.add_argument("--print-rejected", action="store_true", help="Print rejected paths (informational).")
    parser.add_argument("--print-commit-message", action="store_true", help="Print the deterministic commit message body.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    candidates = discover_candidate_paths(repo_root=repo_root)
    result = enumerate_publishable(repo_root=repo_root, candidate_paths=candidates)
    if args.print_paths:
        for path in result.allowed:
            print(path.relative_to(repo_root).as_posix())
    if args.print_rejected:
        for path in result.rejected:
            print(f"REJECTED\t{path.relative_to(repo_root).as_posix()}")
    if args.print_commit_message:
        print(build_commit_message(repo_root=repo_root, paths=result.allowed), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
