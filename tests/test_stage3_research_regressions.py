from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_LICENSING_PATH = REPO_ROOT / "docs" / "research" / "data-licensing.md"
SCRAPING_POLITENESS_PATH = REPO_ROOT / "docs" / "research" / "scraping-politeness.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_georgia_legal_access_section_records_tos_status_and_prohibition_findings():
    text = read(DATA_LICENSING_PATH)

    assert "No reachable Terms of Use or acceptable-use page was found on media.ethics.ga.gov" in text
    assert (
        "No explicit portal prohibition text for automated access, bulk retrieval, or redistribution was found" in text
    )
    assert "Georgia reuse/commercial/redistribution verdict:" in text


def test_colorado_legal_access_section_records_fee_and_permission_constraints():
    text = read(DATA_LICENSING_PATH)

    assert "No fee, purchase flow, or request gate was observed on the public TRACER `DataDownload.aspx` page" in text
    assert "attempted data mining without permission will be blocked" in text
    assert "may not be reproduced in whole or in part without prior written permission" in text


def test_colorado_scraping_guidance_records_blocking_and_capacity_controls():
    text = read(SCRAPING_POLITENESS_PATH)

    assert "attempted data mining from the public website without permission will be blocked" in text
    assert (
        "regulate the duration, timing, and method of data recovery based on available technological capacity" in text
    )
    assert "No documented numeric TRACER bulk-endpoint rate limits were found" in text
