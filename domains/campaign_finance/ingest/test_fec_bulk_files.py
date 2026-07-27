from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.ingest.fec_bulk_files import (
    FEC_DATA_ROOT_ENV_VAR,
    FecDataRootMissingError,
    resolve_fec_data_root,
)

# Covers ONLY data-root resolution. `fec_bulk_data_root` and the URL builders are
# already covered elsewhere (domains/campaign_finance/ingest/test_bulk_cli.py:40-44
# asserts exact values for the former); do not duplicate them here.


def _make_data_root(base: Path) -> Path:
    """Build a directory that satisfies the resolver's `fec/bulk` existence check."""
    data_root = base / "data"
    (data_root / "fec" / "bulk").mkdir(parents=True)
    return data_root


@pytest.mark.unit
def test_env_var_wins_and_returns_the_configured_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = _make_data_root(tmp_path / "configured")
    unused_repo = tmp_path / "repo"
    _make_data_root(unused_repo)
    monkeypatch.setenv(FEC_DATA_ROOT_ENV_VAR, str(configured))

    assert resolve_fec_data_root(repo_root=unused_repo) == configured


@pytest.mark.unit
def test_falls_back_to_repo_root_data_when_env_var_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FEC_DATA_ROOT_ENV_VAR, raising=False)
    expected = _make_data_root(tmp_path)

    assert resolve_fec_data_root(repo_root=tmp_path) == expected
    assert expected == tmp_path / "data"


@pytest.mark.unit
def test_raises_when_repo_root_has_data_but_no_fec_bulk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # This is the live worktree condition: `.gitignore` ignores `data/`, so a
    # worktree has `data/tmp` from test runs but never `data/fec/bulk`.
    monkeypatch.delenv(FEC_DATA_ROOT_ENV_VAR, raising=False)
    (tmp_path / "data" / "tmp").mkdir(parents=True)

    with pytest.raises(FecDataRootMissingError) as excinfo:
        resolve_fec_data_root(repo_root=tmp_path)

    message = str(excinfo.value)
    assert FEC_DATA_ROOT_ENV_VAR in message
    assert str(tmp_path / "data" / "fec" / "bulk") in message


@pytest.mark.unit
def test_raises_when_env_var_points_at_a_root_without_fec_bulk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = tmp_path / "configured"
    configured.mkdir()
    monkeypatch.setenv(FEC_DATA_ROOT_ENV_VAR, str(configured))

    with pytest.raises(FecDataRootMissingError) as excinfo:
        resolve_fec_data_root()

    message = str(excinfo.value)
    assert FEC_DATA_ROOT_ENV_VAR in message
    assert str(configured / "fec" / "bulk") in message


@pytest.mark.unit
def test_default_repo_root_is_the_repository_not_the_domains_package(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pins the fallback depth. Every other test passes `repo_root=` explicitly, so
    # without this a wrong `parents[...]` index ships silently: `parents[2]` from
    # this module yields `<repo>/domains`, and the resolver would look for
    # `<repo>/domains/data/fec/bulk`.
    monkeypatch.delenv(FEC_DATA_ROOT_ENV_VAR, raising=False)
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / "domains" / "campaign_finance").is_dir()

    try:
        resolved = resolve_fec_data_root()
    except FecDataRootMissingError as error:
        # No archives here (a worktree): the message must still name the repo root.
        assert str(repo_root / "data" / "fec" / "bulk") in str(error)
        assert str(repo_root / "domains" / "data") not in str(error)
    else:
        assert resolved == repo_root / "data"
