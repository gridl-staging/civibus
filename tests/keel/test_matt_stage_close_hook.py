from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "matt_stage_close.sh"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_matt_stage_close_hook_runs_gate_from_repo_root(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    log_path = tmp_path / "uv.log"
    _write_executable(
        fake_bin / "uv",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            printf 'cwd=%s\n' "$PWD" > "${UV_LOG_PATH:?}"
            printf 'args=%s\n' "$*" >> "${UV_LOG_PATH:?}"
            exit 0
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["UV_LOG_PATH"] = str(log_path)

    subprocess.run(
        ["bash", str(HOOK_SCRIPT), "--changed-file", "web/src/routes/+page.svelte"],
        check=True,
        cwd=tmp_path,
        env=env,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert f"cwd={REPO_ROOT}" in log_text
    assert "args=run python scripts/stage_close_gate.py --changed-file web/src/routes/+page.svelte" in log_text


def test_matt_stage_close_hook_prefers_matt_project_dir_when_present(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    log_path = tmp_path / "uv.log"
    project_root = tmp_path / "project-root"
    project_root.mkdir()
    _write_executable(
        fake_bin / "uv",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            printf 'cwd=%s\n' "$PWD" > "${UV_LOG_PATH:?}"
            printf 'args=%s\n' "$*" >> "${UV_LOG_PATH:?}"
            exit 0
            """
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["UV_LOG_PATH"] = str(log_path)
    env["MATT_DIR_PROJECT_DIR"] = str(project_root)

    subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        check=True,
        cwd=tmp_path,
        env=env,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert f"cwd={project_root}" in log_text
    assert "args=run python scripts/stage_close_gate.py" in log_text
