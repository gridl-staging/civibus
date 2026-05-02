from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT_PATH = REPO_ROOT / "infra/scripts/bootstrap_l10_gate.sh"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_bootstrap_l10_gate_script_is_executable_thin_wrapper_contract() -> None:
    assert BOOTSTRAP_SCRIPT_PATH.is_file(), "infra/scripts/bootstrap_l10_gate.sh must exist"
    assert os.access(BOOTSTRAP_SCRIPT_PATH, os.X_OK), "infra/scripts/bootstrap_l10_gate.sh must be executable"

    script_text = _read_text(BOOTSTRAP_SCRIPT_PATH)

    assert script_text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script_text
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in script_text
    assert 'repo_root="$(cd "${script_dir}/../.." && pwd)"' in script_text
    assert 'web_dir="${repo_root}/web"' in script_text
    assert 'if ! command -v npm >/dev/null 2>&1; then' in script_text
    assert "npm is required to bootstrap L10 gate dependencies" in script_text
    assert 'lockfile_path="${web_dir}/package-lock.json"' in script_text
    assert 'if [[ ! -f "${lockfile_path}" ]]; then' in script_text
    assert "web/package-lock.json is required for deterministic npm ci" in script_text
    assert 'cd "${web_dir}"' in script_text
    assert "npm ci" in script_text

    forbidden_fragments = (
        "python -m core.keel_gate_l10",
        "make gate-L10",
        "core.keel_gate_l10",
        "evidence/L10",
    )
    for fragment in forbidden_fragments:
        assert fragment not in script_text
