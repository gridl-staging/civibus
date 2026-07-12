from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROBOTS_TXT = REPO_ROOT / "infra" / "Caddyfile"


def test_web_robots_txt_contract():
    assert ROBOTS_TXT.exists(), "Expected web/static/robots.txt to exist."

    robots_text = ROBOTS_TXT.read_text(encoding="utf-8")
    assert "User-agent: *" in robots_text
    assert "Allow: /" in robots_text
    assert "Sitemap:" in robots_text
