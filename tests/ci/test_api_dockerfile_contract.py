from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "infra/api/Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
COMPOSE_PATH = REPO_ROOT / "infra/docker-compose.yml"


def _dockerfile_code(text: str) -> str:
    """Return Dockerfile text with comment lines stripped.

    Used by the runtime-shape assertions below so a comment about a forbidden
    runtime form (e.g. a comment explaining why we removed `uv run`) cannot
    satisfy a "must NOT contain" assertion. The comment-stripping pattern
    matches the one used in tests/ci/test_recover_apr30_volume_script.py
    (`script_code` fixture) — same false-positive concern, same fix.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_api_dockerfile_contract_inputs_and_entrypoint() -> None:
    assert DOCKERFILE_PATH.is_file(), "infra/api/Dockerfile must exist"

    dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    dockerfile_code = _dockerfile_code(dockerfile_text)

    # Build inputs: source dirs + lockfile must be present so `uv sync` resolves.
    assert "COPY pyproject.toml uv.lock ./" in dockerfile_text
    assert "COPY api ./api" in dockerfile_text
    assert "COPY core ./core" in dockerfile_text
    assert "COPY domains ./domains" in dockerfile_text
    assert "uv sync --locked --extra api" in dockerfile_text

    # Runtime CMD must NOT use `uv run`. `uv run` re-syncs the venv on every
    # container start, which fails for the non-root `civibus` user because the
    # venv was created by root during build (see Dockerfile CMD comment + the
    # 2026-05-01 :latest image bug postmortem in
    # docs/research/2026_05_01_pre_launch_scope_audit.md). The CMD must call
    # uvicorn directly via the venv's PATH.
    assert "uv run" not in dockerfile_code, (
        "CMD must call uvicorn directly via PATH, not `uv run` (the latter "
        "re-syncs the venv at runtime, which fails as user `civibus`)"
    )
    assert 'CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]' in dockerfile_code

    # User isolation: must run as a non-root user.
    assert "USER " in dockerfile_code
    assert "USER root" not in dockerfile_code

    # `python -m ...` should NOT appear in the Dockerfile body. The entrypoint
    # script (docker-entrypoint.sh) is the ONLY runtime invocation surface, and
    # it lives at infra/api/docker-entrypoint.sh — not in the Dockerfile.
    assert "python -m" not in dockerfile_code


def test_dockerignore_excludes_non_runtime_paths() -> None:
    assert DOCKERIGNORE_PATH.is_file(), ".dockerignore must exist at repo root"

    dockerignore_text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    for ignored_path in (".git/", ".env", ".env.*", "tests/", "docs/", "*.pyc", "infra/scripts/backups/"):
        assert ignored_path in dockerignore_text


def test_stage6_source_of_truth_contracts_remain_unchanged() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert (
        "api-dev: require-postgres-password\n"
        "\tuv run --extra dev --extra api uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload"
    ) in makefile_text
    assert "python -m api.main" not in makefile_text

    assert "dockerfile: infra/db/Dockerfile" in compose_text
    assert "infra/api/Dockerfile" not in compose_text
    assert "  api:" not in compose_text
