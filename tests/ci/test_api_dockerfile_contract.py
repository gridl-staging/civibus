from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "infra/api/Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
COMPOSE_PATH = REPO_ROOT / "infra/docker-compose.yml"


def test_api_dockerfile_contract_inputs_and_entrypoint() -> None:
    assert DOCKERFILE_PATH.is_file(), "infra/api/Dockerfile must exist"

    dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "COPY pyproject.toml uv.lock ./" in dockerfile_text
    assert "COPY api ./api" in dockerfile_text
    assert "COPY core ./core" in dockerfile_text
    assert "COPY domains ./domains" in dockerfile_text
    assert "uv sync --locked --extra api" in dockerfile_text
    assert 'CMD ["uv", "run", "--extra", "api", "uvicorn", "api.main:app"' in dockerfile_text
    assert "USER " in dockerfile_text
    assert "USER root" not in dockerfile_text
    assert "python -m" not in dockerfile_text


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
