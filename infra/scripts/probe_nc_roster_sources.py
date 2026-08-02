"""Independent re-fetch probe for the Stage 2 NC roster disposition artifact.

Verification-only: this is NOT a new acquisition pipeline. It re-reads the committed
disposition JSON, deterministically samples working/repaired entries by sorted job key,
re-fetches each through the SAME shared HTTP contract the loader uses
(core.people.enrichment.strategy_shared.DEFAULT_HTTP_HEADERS, matching
fetch_bytes_via_http()), re-parses with parse_roster_rows(), and confirms the recorded
disposition still agrees with a fresh fetch. It adds no retries, proxying, or UA
workarounds and never writes to the database.

Prints one machine-checkable summary line:

    nc_roster_refetch: sampled=<n> agreed=<n> disagreed=<n>

Exit status is non-zero when any sampled entry disagrees, when the requested sample
cannot be filled (so sampled=0 is never a vacuous pass), or when fewer than the required
floor of working/repaired-with-rows entries exist in the artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS
from domains.civics.loaders.official_rosters.parsers import parse_roster_rows

_WORKING_DISPOSITIONS = {"working", "repaired"}
_DEFAULT_SAMPLE = 8
_DEFAULT_MIN_WORKING_FLOOR = 15
_FETCH_TIMEOUT_SECONDS = 30.0

# A fetcher returns (http_status, response_text) so tests can inject responses.
Fetch = Callable[[str], "tuple[int, str]"]


@dataclass(frozen=True)
class EntryOutcome:
    job_key: str
    agreed: bool
    note: str


@dataclass(frozen=True)
class ProbeResult:
    sampled: int
    agreed: int
    disagreed: int
    working_with_rows: int
    outcomes: tuple[EntryOutcome, ...]

    @property
    def summary_line(self) -> str:
        return f"nc_roster_refetch: sampled={self.sampled} agreed={self.agreed} disagreed={self.disagreed}"


def default_fetch(url: str) -> tuple[int, str]:
    """Re-fetch public HTTPS roster pages without allowing redirect-based SSRF."""
    import socket
    from ipaddress import ip_address
    from urllib.parse import urljoin, urlparse

    def validate_destination(candidate_url: str) -> None:
        parsed = urlparse(candidate_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Roster probe destinations must use public HTTPS on port 443") from exc
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme.casefold() != "https"
            or hostname == ""
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or hostname == "localhost"
            or hostname.endswith((".localhost", ".local", ".internal", ".home.arpa"))
        ):
            raise ValueError("Roster probe destinations must use public HTTPS on port 443")

        try:
            literal_address = ip_address(hostname)
        except ValueError:
            literal_address = None
        if literal_address is not None:
            if not literal_address.is_global or literal_address.is_multicast:
                raise ValueError("Roster probe destinations must use public HTTPS on port 443")
            return

        try:
            resolved_addresses = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("Roster probe destination hostname did not resolve") from exc
        resolved_ip_addresses = [ip_address(address[4][0].split("%", maxsplit=1)[0]) for address in resolved_addresses]
        if not resolved_ip_addresses or any(
            not address.is_global or address.is_multicast for address in resolved_ip_addresses
        ):
            raise ValueError("Roster probe destinations must use public HTTPS on port 443")

    current_url = url
    for _ in range(6):
        validate_destination(current_url)
        response = httpx.get(
            current_url,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )
        if not response.is_redirect:
            return response.status_code, response.text
        location = response.headers.get("location")
        if location is None:
            return response.status_code, response.text
        current_url = urljoin(str(response.url), location)
    raise ValueError("Roster probe exceeded five redirects")


def load_dispositions(path: Path) -> dict[str, dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_sample(dispositions: dict[str, dict[str, object]], sample_size: int) -> list[str]:
    """Deterministically pick working/repaired job keys sorted lexicographically.

    Sorting fixes the sample so it cannot be hand-picked to hide a broken source.
    """
    working_keys = sorted(
        job_key for job_key, entry in dispositions.items() if entry.get("disposition") in _WORKING_DISPOSITIONS
    )
    return working_keys[:sample_size]


def count_working_with_rows(dispositions: dict[str, dict[str, object]]) -> int:
    return sum(
        1
        for entry in dispositions.values()
        if entry.get("disposition") in _WORKING_DISPOSITIONS and int(entry.get("rows_parsed") or 0) > 0
    )


def refetch_entry(entry: dict[str, object], fetch: Fetch) -> tuple[bool, str]:
    """Return (agreed, note); a recorded non-200 fails before any live fetch."""
    if entry.get("http_status") != 200:
        return False, f"recorded http_status {entry.get('http_status')} is not 200"
    try:
        live_status, live_text = fetch(str(entry["source_url"]))
    except Exception as exc:
        return False, f"live fetch failed: {type(exc).__name__}: {exc}"
    if live_status == 202 or not 200 <= live_status < 300:
        return False, f"live fetch returned {live_status}"
    try:
        live_rows = parse_roster_rows(
            body_key=str(entry["body_key"]),
            source_url=str(entry["source_url"]),
            html=live_text,
        )
    except Exception as exc:
        return False, f"live parse failed: {type(exc).__name__}: {exc}"
    recorded_rows = int(entry.get("rows_parsed") or 0)
    # Exact equality, not just "still non-empty": a recorded count that no longer matches a
    # fresh parse is stale or wrong evidence, and the artifact must not be approved on it.
    if len(live_rows) != recorded_rows:
        return False, f"recorded rows_parsed {recorded_rows} but live re-parse yielded {len(live_rows)} rows"
    return True, f"agreed (live rows={len(live_rows)})"


def run_probe(
    dispositions: dict[str, dict[str, object]],
    *,
    sample_size: int,
    fetch: Fetch,
) -> ProbeResult:
    sampled_keys = select_sample(dispositions, sample_size)
    outcomes: list[EntryOutcome] = []
    for job_key in sampled_keys:
        agreed, note = refetch_entry(dispositions[job_key], fetch)
        outcomes.append(EntryOutcome(job_key=job_key, agreed=agreed, note=note))
    agreed_count = sum(1 for outcome in outcomes if outcome.agreed)
    return ProbeResult(
        sampled=len(outcomes),
        agreed=agreed_count,
        disagreed=len(outcomes) - agreed_count,
        working_with_rows=count_working_with_rows(dispositions),
        outcomes=tuple(outcomes),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispositions", required=True, type=Path)
    parser.add_argument("--sample", type=int, default=_DEFAULT_SAMPLE)
    parser.add_argument("--min-working", type=int, default=_DEFAULT_MIN_WORKING_FLOOR)
    args = parser.parse_args(argv)
    if args.sample <= 0:
        parser.error("--sample must be greater than zero")
    if args.min_working < 0:
        parser.error("--min-working must be zero or greater")
    return args


def main(argv: list[str] | None = None, *, fetch: Fetch = default_fetch) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    dispositions = load_dispositions(args.dispositions)
    result = run_probe(dispositions, sample_size=args.sample, fetch=fetch)

    for outcome in result.outcomes:
        print(f"  {outcome.job_key}: {'AGREE' if outcome.agreed else 'DISAGREE'} — {outcome.note}")
    print(result.summary_line)
    print(f"nc_roster_working_floor: working_with_rows={result.working_with_rows} required={args.min_working}")

    ok = True
    if result.sampled < args.sample:
        print(f"FAIL: requested sample {args.sample} but only {result.sampled} working/repaired entries available")
        ok = False
    if result.disagreed > 0:
        print(f"FAIL: {result.disagreed} sampled entries disagreed with the recorded disposition")
        ok = False
    if result.working_with_rows < args.min_working:
        print(
            "FAIL: lane verdict NO — only "
            f"{result.working_with_rows} working/repaired entries have rows (floor {args.min_working})"
        )
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
