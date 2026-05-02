from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

from domains.campaign_finance.jurisdictions.states.CA.scraper import cli


def _set_dir_age_seconds(directory: Path, *, seconds_old: int) -> None:
    stale_timestamp = time.time() - seconds_old
    os.utime(directory, (stale_timestamp, stale_timestamp))


def test_purges_stale_ca_download_dir(tmp_path: Path) -> None:
    stale_dir = tmp_path / "ca-download-stale"
    stale_dir.mkdir()
    _set_dir_age_seconds(stale_dir, seconds_old=48 * 3600)

    removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert stale_dir.name in removed
    assert not stale_dir.exists()


def test_preserves_recent_ca_download_dir(tmp_path: Path) -> None:
    recent_dir = tmp_path / "ca-download-recent"
    recent_dir.mkdir()
    _set_dir_age_seconds(recent_dir, seconds_old=5 * 60)

    removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert removed == []
    assert recent_dir.exists()


def test_purges_stale_ca_archive_dir(tmp_path: Path) -> None:
    stale_dir = tmp_path / "ca-archive-stale"
    stale_dir.mkdir()
    _set_dir_age_seconds(stale_dir, seconds_old=48 * 3600)

    removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert stale_dir.name in removed
    assert not stale_dir.exists()


def test_ignores_unrelated_dirs(tmp_path: Path) -> None:
    unrelated_dir = tmp_path / "other-temp-dir"
    unrelated_dir.mkdir()
    _set_dir_age_seconds(unrelated_dir, seconds_old=48 * 3600)

    removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert removed == []
    assert unrelated_dir.exists()


def test_preserves_dir_with_live_handle(tmp_path: Path) -> None:
    stale_dir = tmp_path / "ca-download-live"
    stale_dir.mkdir()
    handle_path = stale_dir / "active-file.txt"
    handle_path.write_text("active", encoding="utf-8")
    _set_dir_age_seconds(stale_dir, seconds_old=48 * 3600)

    fake_process = SimpleNamespace(open_files=lambda: [SimpleNamespace(path=str(handle_path))])

    first_removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [fake_process],
    )
    second_removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert first_removed == []
    assert stale_dir.name in second_removed
    assert not stale_dir.exists()


def test_logs_what_was_removed(tmp_path: Path) -> None:
    stale_download_dir = tmp_path / "ca-download-loggable"
    stale_archive_dir = tmp_path / "ca-archive-loggable"
    stale_download_dir.mkdir()
    stale_archive_dir.mkdir()
    _set_dir_age_seconds(stale_download_dir, seconds_old=48 * 3600)
    _set_dir_age_seconds(stale_archive_dir, seconds_old=48 * 3600)

    log_messages: list[str] = []

    cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        logger=log_messages.append,
        process_iter=lambda *args, **kwargs: [],
    )

    joined_messages = "\n".join(log_messages)
    assert stale_download_dir.name in joined_messages
    assert stale_archive_dir.name in joined_messages


def test_is_idempotent(tmp_path: Path) -> None:
    stale_dir = tmp_path / "ca-download-idempotent"
    stale_dir.mkdir()
    _set_dir_age_seconds(stale_dir, seconds_old=48 * 3600)

    first_removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )
    second_removed = cli._purge_stale_ca_temp_dirs(
        tempdir_root=tmp_path,
        process_iter=lambda *args, **kwargs: [],
    )

    assert stale_dir.name in first_removed
    assert second_removed == []
