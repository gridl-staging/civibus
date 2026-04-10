"""CI repo coverage contract tests for Stage 3 coverage enforcement."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
UV_LOCK_PATH = REPO_ROOT / "uv.lock"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


def test_pyproject_dev_dependencies_include_pytest_cov() -> None:
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")

    assert '"pytest-cov"' in pyproject_text


def test_uv_lock_includes_pytest_cov_package_and_dev_marker() -> None:
    uv_lock_text = UV_LOCK_PATH.read_text(encoding="utf-8")

    assert 'name = "pytest-cov"' in uv_lock_text
    assert '{ name = "pytest-cov", marker = "extra == \'dev\'" }' in uv_lock_text


def test_gitignore_ignores_coverage_artifacts() -> None:
    gitignore_text = GITIGNORE_PATH.read_text(encoding="utf-8")

    assert ".coverage" in gitignore_text
    assert "htmlcov/" in gitignore_text
