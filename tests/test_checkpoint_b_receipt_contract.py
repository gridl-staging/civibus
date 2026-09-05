from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = REPO_ROOT / "docs" / "live-state" / "2026_08_25_checkpoint_b_receipt.md"
CLOSEOUT_RECEIPT_PATH = REPO_ROOT / "docs" / "live-state" / "2026_08_25_aug15_campaign_checkpoint_b_receipt.md"
LAUNCH_KIT_PATH = REPO_ROOT / "chats" / "promotion" / "2026_08_launch_kit.md"
CAPABILITIES_PATH = REPO_ROOT / "CAPABILITIES.md"


REQUIRED_RECEIPT_TOKENS = (
    "# 2026-08-25 -- Checkpoint B receipt: reliable without a human gate",
    "**Gate:** Checkpoint B for `civibus-ehu`",
    "**Verdict: CHECKPOINT B RED.",
    "## Claims",
    "## Acceptance probes, run fresh in one session (verbatim)",
    "## Decision menu",
    "`civibus-refresh` Machine `859e0da479e678`",
    "`core.refresh_run`",
    "`core.data_source`",
    "$ flyctl status -a civibus-refresh --json",
    "$ flyctl machine status 859e0da479e678 -a civibus-refresh",
    "$ gh run view",
    "event=schedule",
    "browser-smoke",
    "person_resilience.spec.ts",
    "test_support/browser_smoke_seed.py",
    "$ uv run pytest tests/test_beads_adoption_contract.py -q",
    "test_pinned_bd_cli_version_is_exact",
    "$ bd where --json",
    "$ python3 scripts/uptime_incident_bridge.py",
    "uptime incident bridge completed:",
    "Lane HEAD:",
)


def collapse_markdown_wrapping(text: str) -> str:
    """Collapse every whitespace run to one space.

    These documents are hard-wrapped, so a claim phrase routinely straddles a
    line break. Matching against the raw text would both miss a wrapped
    forbidden phrase and fail on a wrapped required phrase, so every
    prose-level assertion in this contract matches the collapsed form.
    """
    return " ".join(text.split())


def test_checkpoint_b_receipt_records_fresh_gate_evidence_and_red_menu() -> None:
    receipt_text = RECEIPT_PATH.read_text(encoding="utf-8")

    missing_tokens = [token for token in REQUIRED_RECEIPT_TOKENS if token not in receipt_text]
    assert missing_tokens == []

    assert "<DD>" not in RECEIPT_PATH.name
    assert "2x" not in RECEIPT_PATH.name
    assert "<DD>" not in receipt_text
    assert "2026_08_2x_checkpoint_b_receipt" not in receipt_text
    assert "matt:pinned-receipt-sha" not in receipt_text
    assert "/Users/" not in receipt_text
    assert '"database_path": "<redacted-local-root>/.beads/embeddeddolt"' in receipt_text
    assert '"path": "<redacted-local-root>/.beads"' in receipt_text


def test_aug15_closeout_preserves_the_red_verdict_without_private_paths() -> None:
    """Keep the historical verdict honest while recording later recovery."""
    receipt_text = CLOSEOUT_RECEIPT_PATH.read_text(encoding="utf-8")
    normalized_receipt = collapse_markdown_wrapping(receipt_text)

    assert "**Verdict:** `CHECKPOINT B RED`." in receipt_text
    assert "/Users/" not in receipt_text
    assert ".matt/projects/" not in receipt_text
    assert "unattended and autonomy claims remain embargoed" in normalized_receipt
    assert "gridl-hq/civibus#7" in receipt_text
    assert "2026-08-26T01:26:17Z" in receipt_text
    assert "gridl-staging/civibus#9" in receipt_text
    assert "2026-08-26T01:49:07Z" in receipt_text
    assert "civibus-4th" in receipt_text
    assert "2026-09-01T18:53:21Z" in receipt_text


def test_checkpoint_b_receipt_probes_first_post_sync_scheduled_nightly() -> None:
    receipt_text = RECEIPT_PATH.read_text(encoding="utf-8")

    first_post_sync_section = receipt_text.split("#### First scheduled run after `civibus-ehu.1` closure", maxsplit=1)[
        -1
    ].split("#### Latest scheduled run", maxsplit=1)[0]

    assert first_post_sync_section != receipt_text
    assert "2026-08-21T22:06:07Z" in first_post_sync_section
    assert "$ gh run view 32559443130" in first_post_sync_section
    assert "url=https://github.com/gridl-staging/civibus/actions/runs/32559443130" in first_post_sync_section
    assert "event=schedule" in first_post_sync_section
    assert "headSha=c7c16dc9e5e0f5f9f6a4d6ebb30f856d33c8d270" in first_post_sync_section
    assert "browser-smoke job=96998672668 conclusion=failure" in first_post_sync_section
    assert "Seed browser-smoke live data conclusion=success" in first_post_sync_section
    assert "Browser smoke journeys conclusion=failure" in first_post_sync_section
    assert (
        "web/tests/smoke/person_resilience.spec.ts 296ed13ae4f916f7621bb745bd2738b3813ec3e3" in first_post_sync_section
    )
    assert "test_support/browser_smoke_seed.py fc6bd3f56ebd5c70b928578e1f934cc5fc083ad6" in first_post_sync_section
    assert "Process completed with exit code 1." in first_post_sync_section


def test_bridge_claim_uses_the_assembly_time_execution_head() -> None:
    receipt_text = RECEIPT_PATH.read_text(encoding="utf-8")

    gate_window_head = re.search(
        r"\*\*Gate window:\*\*.*?lane HEAD\s+`([0-9a-f]{40})`\.",
        receipt_text,
        flags=re.DOTALL,
    )
    bridge_execution_head = re.search(
        r"Bridge revision observed: assembly-time lane HEAD `([0-9a-f]{40})` executing",
        receipt_text,
    )
    receipt_documentation_revision = re.search(
        r"Receipt documentation revision: `([0-9a-f]{40})`",
        receipt_text,
    )

    assert gate_window_head is not None
    assert bridge_execution_head is not None
    assert receipt_documentation_revision is not None
    assert bridge_execution_head.group(1) == gate_window_head.group(1)
    assert receipt_documentation_revision.group(1) != bridge_execution_head.group(1)


def test_checkpoint_b_promotion_is_limited_to_the_receipt_licensed_bridge_loop() -> None:
    launch_kit_text = LAUNCH_KIT_PATH.read_text(encoding="utf-8")
    capabilities_text = CAPABILITIES_PATH.read_text(encoding="utf-8")
    normalized_capabilities_text = collapse_markdown_wrapping(capabilities_text)

    assert "CHECKPOINT B RED" in launch_kit_text
    assert "docs/live-state/2026_08_25_checkpoint_b_receipt.md" in launch_kit_text
    assert (
        "The uptime incident bridge loop creates or updates Beads from trusted upstream uptime evidence."
    ) in launch_kit_text
    assert "The promoted bridge-loop claim cites no public HTTP(S) URL." in launch_kit_text

    assert "docs/live-state/2026_08_25_checkpoint_b_receipt.md" in capabilities_text
    assert "Checkpoint B remains red and autonomy claims remain absent" in capabilities_text
    assert "creates or updates Beads from trusted upstream uptime evidence" in normalized_capabilities_text


def test_autonomy_phrases_appear_only_in_explicitly_red_or_embargoed_context() -> None:
    forbidden_autonomy_phrases = (
        "stays fresh automatically",
        "reliable without a human",
        "self-updating",
        "always current",
        "production-grade uptime",
    )
    safe_context_markers = (
        "autonomy claims remain absent",
        "checkpoint b red",
        "does not license",
        "embargoed",
        "not licensed",
    )

    for path in (LAUNCH_KIT_PATH, CAPABILITIES_PATH):
        paragraphs = [
            collapse_markdown_wrapping(paragraph).casefold()
            for paragraph in re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))
        ]
        unsafe_occurrences = [
            phrase
            for paragraph in paragraphs
            for phrase in forbidden_autonomy_phrases
            if phrase in paragraph and not any(marker in paragraph for marker in safe_context_markers)
        ]
        assert unsafe_occurrences == [], f"{path}: {unsafe_occurrences}"
