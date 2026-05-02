from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POST_SYNC_SCRIPT = REPO_ROOT / ".debbie" / "post-sync.sh"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_post_sync_removes_todo_scaffolds_when_strip_is_noop(tmp_path: Path) -> None:
    target_root = tmp_path / "staging"
    target_root.mkdir()

    python_file = target_root / "core" / "example.py"
    shell_file = target_root / "infra" / "env_lib.sh"
    python_file.parent.mkdir(parents=True, exist_ok=True)
    shell_file.parent.mkdir(parents=True, exist_ok=True)

    fake_bin = tmp_path / "fake-bin"
    _write_executable(
        fake_bin / "matt",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            if [[ "${1:-}" == "scrai" && "${2:-}" == "strip" && "${3:-}" == "--help" ]]; then
              exit 0
            fi
            if [[ "${1:-}" == "scrai" && "${2:-}" == "strip" ]]; then
              exit 0
            fi
            exit 1
            """
        ),
    )

    env = os.environ.copy()
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env.pop("MATT_REPO_ROOT", None)

    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], check=True, env=env)



def test_post_sync_uses_repo_virtualenv_python_when_python3_fails(tmp_path: Path) -> None:
    target_root = tmp_path / "staging"
    target_root.mkdir()

    python_file = target_root / "core" / "example.py"
    python_file.parent.mkdir(parents=True, exist_ok=True)

    matt_repo = tmp_path / "mike_dev"
    strip_module = matt_repo / "matt_root" / "matt" / "scrai" / "strip.py"
    strip_module.parent.mkdir(parents=True, exist_ok=True)
    strip_module.write_text("# fixture module marker\n", encoding="utf-8")

    venv_log = tmp_path / "venv-python.log"
    _write_executable(
        matt_repo / ".venv" / "bin" / "python",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            if [[ "${1:-}" == "-m" && "${2:-}" == "matt" && "${3:-}" == "scrai" && "${4:-}" == "strip" ]]; then
              printf '%s\n' "$*" >> "${VENV_PYTHON_LOG:?}"
              exit 0
            fi
            exit 1
            """
        ),
    )

    fake_bin = tmp_path / "fake-bin"
    _write_executable(fake_bin / "python3", "#!/bin/bash\nexit 1\n")
    _write_executable(fake_bin / "matt", "#!/bin/bash\nexit 1\n")

    env = os.environ.copy()
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["MATT_REPO_ROOT"] = str(matt_repo)
    env["VENV_PYTHON_LOG"] = str(venv_log)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], check=True, env=env)

    assert venv_log.exists()
    log_text = venv_log.read_text(encoding="utf-8")
    assert "-m matt scrai strip --help" in log_text
