from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest import bulk_cli
from domains.campaign_finance.ingest.bulk_loader import LoadResult, Stage4LoadOptions


def _build_connection() -> MagicMock:
    connection = MagicMock()
    connection.transaction.side_effect = lambda: nullcontext()
    return connection


@pytest.mark.unit
def test_validate_cli_arguments_accepts_single_file_mode(tmp_path: Path) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")

    parser = bulk_cli.build_argument_parser()
    args = parser.parse_args(["--cycle", "2024", "--file-type", "cm", "--path", str(file_path)])

    config = bulk_cli.validate_cli_arguments(args)

    assert config.mode == "single"
    assert config.path == file_path
    assert config.file_type == "cm"
    assert config.directory is None
    assert config.canonical_stage4_resume_enabled is False


@pytest.mark.unit
def test_validate_cli_arguments_marks_cli_full_cycle_as_canonical_stage4_resume_owner(tmp_path: Path) -> None:
    for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
        (tmp_path / f"{file_type}_sample.txt").write_text("", encoding="latin-1")

    parser = bulk_cli.build_argument_parser()
    args = parser.parse_args(["--cycle", "2024", "--all", "--directory", str(tmp_path)])

    config = bulk_cli.validate_cli_arguments(args)

    assert config.mode == "full"
    assert config.directory == tmp_path
    assert config.canonical_stage4_resume_enabled is True


@pytest.mark.unit
def test_schedule_e_is_registered_as_a_stage3_loader() -> None:
    assert "schedule_e" in bulk_cli.FILE_TYPES
    schedule_e_loader = bulk_cli.FILE_TYPE_LOADERS["schedule_e"]

    assert schedule_e_loader.requires_cycle is True
    assert schedule_e_loader.supports_graph is True


@pytest.mark.unit
def test_committee_summary_is_registered_as_cycle_aware_csv_loader(tmp_path: Path) -> None:
    assert "committee_summary" in bulk_cli.FILE_TYPES
    assert "committee_summary" not in bulk_cli.FULL_CYCLE_FILE_ORDER

    committee_summary_loader = bulk_cli.FILE_TYPE_LOADERS["committee_summary"]
    assert committee_summary_loader.requires_cycle is True
    assert committee_summary_loader.supports_graph is False
    assert bulk_cli._matches_file_type(Path("committee_summary_2024.csv"), "committee_summary")
    assert not bulk_cli._matches_file_type(Path("committee_summary_2024.zip"), "committee_summary")

    expected_federal_paths = {
        "cm": tmp_path / "cm24.zip",
        "cn": tmp_path / "cn24.zip",
        "ccl": tmp_path / "ccl24.zip",
        "weball": tmp_path / "weball24.zip",
        "committee_summary": tmp_path / "committee_summary_2024.csv",
        "schedule_e": tmp_path / "independent_expenditure_2024.csv",
    }
    for path in expected_federal_paths.values():
        path.write_text("", encoding="latin-1")

    resolved = bulk_cli.resolve_federal_ingest_directory(tmp_path)

    assert resolved == expected_federal_paths


@pytest.mark.unit
def test_schedule_b_is_registered_as_a_stage3_loader() -> None:
    assert "schedule_b" in bulk_cli.FILE_TYPES
    schedule_b_loader = bulk_cli.FILE_TYPE_LOADERS["schedule_b"]

    assert schedule_b_loader.requires_cycle is True
    assert schedule_b_loader.supports_graph is True


@pytest.mark.unit
def test_weball_is_registered_as_single_file_candidate_summary_loader(tmp_path: Path) -> None:
    assert "weball" in bulk_cli.FILE_TYPES
    weball_loader = bulk_cli.FILE_TYPE_LOADERS["weball"]
    file_path = tmp_path / "weball24.zip"
    file_path.write_text("", encoding="latin-1")
    parser = bulk_cli.build_argument_parser()
    args = parser.parse_args(["--cycle", "2024", "--file-type", "weball", "--path", str(file_path)])

    config = bulk_cli.validate_cli_arguments(args)

    assert weball_loader.requires_cycle is True
    assert weball_loader.supports_graph is False
    assert config.mode == "single"
    assert config.file_type == "weball"
    assert config.path == file_path
    assert bulk_cli._matches_file_type(Path("weball24.zip"), "weball")


@pytest.mark.unit
def test_weball_stays_out_of_full_cycle_and_baseline_url_helpers() -> None:
    assert "weball" not in bulk_cli.FULL_CYCLE_FILE_ORDER
    assert "weball" not in bulk_cli.fec_baseline_urls(2024)
    with pytest.raises(ValueError, match="Unknown FEC file type"):
        bulk_cli.fec_baseline_url(2024, "weball")
    assert "itpas2" in bulk_cli.FILE_TYPE_LOADERS
    assert "pas2" not in bulk_cli.FILE_TYPE_LOADERS
    assert bulk_cli.fec_baseline_url(2024, "itpas2").endswith("/pas224.zip")


@pytest.mark.unit
def test_federal_ingest_order_excludes_itcont_without_changing_full_cycle(tmp_path: Path) -> None:
    expected_federal_paths = {
        "cm": tmp_path / "cm24.zip",
        "cn": tmp_path / "cn24.zip",
        "ccl": tmp_path / "ccl24.zip",
        "weball": tmp_path / "weball24.zip",
        "committee_summary": tmp_path / "committee_summary_2024.csv",
        "schedule_e": tmp_path / "independent_expenditure_2024.csv",
    }
    for path in [*expected_federal_paths.values(), tmp_path / "indiv24.zip", tmp_path / "pas224.zip"]:
        path.write_text("", encoding="latin-1")

    resolved = bulk_cli.resolve_federal_ingest_directory(tmp_path)

    assert bulk_cli.FEDERAL_INGEST_FILE_ORDER == ("cm", "cn", "ccl", "weball", "committee_summary", "schedule_e")
    assert "itcont" not in bulk_cli.FEDERAL_INGEST_FILE_ORDER
    assert "itpas2" not in bulk_cli.FEDERAL_INGEST_FILE_ORDER
    assert bulk_cli.FULL_CYCLE_FILE_ORDER == ("cm", "cn", "ccl", "itcont", "itpas2")
    assert list(resolved) == list(bulk_cli.FEDERAL_INGEST_FILE_ORDER)
    assert resolved == expected_federal_paths
    assert bulk_cli.resolve_full_cycle_directory(tmp_path)["itcont"] == tmp_path / "indiv24.zip"


@pytest.mark.unit
def test_validate_cli_arguments_handles_with_transactions_flag(tmp_path: Path) -> None:
    itcont_path = tmp_path / "itcont_sample.txt"
    itcont_path.write_text("", encoding="latin-1")
    cm_path = tmp_path / "cm_sample.txt"
    cm_path.write_text("", encoding="latin-1")
    parser = bulk_cli.build_argument_parser()

    default_args = parser.parse_args(["--cycle", "2024", "--file-type", "itcont", "--path", str(itcont_path)])
    enabled_args = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "itcont",
            "--path",
            str(itcont_path),
            "--with-transactions",
        ]
    )
    unsupported_args = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(cm_path),
            "--with-transactions",
        ]
    )

    default_config = bulk_cli.validate_cli_arguments(default_args)
    enabled_config = bulk_cli.validate_cli_arguments(enabled_args)

    assert default_config.with_transactions is False
    assert enabled_config.with_transactions is True
    with pytest.raises(ValueError, match="supported only for itcont and itpas2"):
        bulk_cli.validate_cli_arguments(unsupported_args)


@pytest.mark.unit
def test_validate_cli_arguments_accepts_download_and_bounded_schedule_a_flags() -> None:
    parser = bulk_cli.build_argument_parser()
    args = parser.parse_args(
        [
            "--cycle",
            "2026",
            "--file-type",
            "itcont",
            "--download",
            "--transactions-only",
            "--spine-only",
            "--min-date",
            "2022-01-01",
            "--count-only",
        ]
    )

    config = bulk_cli.validate_cli_arguments(args)

    assert config.mode == "single"
    assert config.download is True
    assert config.transactions_only is True
    assert config.spine_only is True
    assert config.min_date == date(2022, 1, 1)
    assert config.count_only is True


@pytest.mark.unit
def test_validate_cli_arguments_rejects_invalid_bounded_schedule_a_flag_combinations(tmp_path: Path) -> None:
    parser = bulk_cli.build_argument_parser()
    schedule_b_path = tmp_path / "schedule_b.zip"
    schedule_b_path.write_text("", encoding="latin-1")
    itcont_path = tmp_path / "itcont_sample.txt"
    itcont_path.write_text("", encoding="latin-1")

    with pytest.raises(ValueError, match="mutually exclusive"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--file-type",
                    "itcont",
                    "--path",
                    str(itcont_path),
                    "--download",
                ]
            )
        )

    with pytest.raises(ValueError, match="spine-only is supported only for itcont"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--file-type",
                    "schedule_b",
                    "--path",
                    str(schedule_b_path),
                    "--spine-only",
                ]
            )
        )

    with pytest.raises(ValueError, match="count-only is supported only in single-file transaction mode"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--all",
                    "--directory",
                    str(tmp_path),
                    "--count-only",
                ]
            )
        )

    with pytest.raises(ValueError, match="min-date is supported only in single-file transaction mode"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--federal",
                    "--directory",
                    str(tmp_path),
                    "--min-date",
                    "2022-01-01",
                ]
            )
        )


@pytest.mark.unit
def test_validate_cli_arguments_rejects_download_with_directory_mode(tmp_path: Path) -> None:
    """--download is single-file only; combining it with directory mode must be rejected."""
    parser = bulk_cli.build_argument_parser()

    with pytest.raises(ValueError, match="single-file mode and directory mode are mutually exclusive"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--download",
                    "--all",
                    "--directory",
                    str(tmp_path),
                ]
            )
        )


@pytest.mark.unit
def test_validate_cli_arguments_rejects_min_date_for_non_transaction_single_file_type(tmp_path: Path) -> None:
    """--min-date is transaction-only; single-file cm mode must reject it."""
    parser = bulk_cli.build_argument_parser()
    cm_path = tmp_path / "cm_sample.txt"
    cm_path.write_text("", encoding="latin-1")

    with pytest.raises(
        ValueError,
        match="--with-transactions, --transactions-only, --min-date, and --count-only are supported only for itcont and itpas2",
    ):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--file-type",
                    "cm",
                    "--path",
                    str(cm_path),
                    "--min-date",
                    "2022-01-01",
                ]
            )
        )


@pytest.mark.unit
def test_validate_cli_arguments_rejects_count_only_for_non_transaction_single_file_type(tmp_path: Path) -> None:
    """--count-only is transaction-only; single-file cm mode must reject it."""
    parser = bulk_cli.build_argument_parser()
    cm_path = tmp_path / "cm_sample.txt"
    cm_path.write_text("", encoding="latin-1")

    with pytest.raises(
        ValueError,
        match="--with-transactions, --transactions-only, --min-date, and --count-only are supported only for itcont and itpas2",
    ):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--file-type",
                    "cm",
                    "--path",
                    str(cm_path),
                    "--count-only",
                ]
            )
        )


@pytest.mark.unit
def test_validate_cli_arguments_rejects_transactions_only_with_directory_mode(tmp_path: Path) -> None:
    """--transactions-only is single-file only; combining with --all --directory must be rejected."""
    parser = bulk_cli.build_argument_parser()

    with pytest.raises(ValueError, match="transactions-only is supported only in single-file transaction mode"):
        bulk_cli.validate_cli_arguments(
            parser.parse_args(
                [
                    "--cycle",
                    "2026",
                    "--all",
                    "--directory",
                    str(tmp_path),
                    "--transactions-only",
                ]
            )
        )


@pytest.mark.unit
def test_dispatch_load_transactions_only_forces_with_transactions_and_disables_entity_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when --with-transactions is omitted, --transactions-only must imply with_transactions=True
    and entity_extraction=False in the Stage4LoadOptions built by dispatch_load."""
    data_source_id = uuid4()
    fake_connection = object()
    file_path = tmp_path / "itcont_sample.txt"
    file_path.write_text("", encoding="latin-1")
    captured_options: list[Stage4LoadOptions] = []

    def stage4_loader(conn, path, *, cycle, data_source_id, options):
        del conn, path, cycle, data_source_id
        captured_options.append(options)
        return LoadResult(inserted=0, skipped=0, errors=0)

    monkeypatch.setattr(
        bulk_cli,
        "FILE_TYPE_LOADERS",
        {"itcont": bulk_cli.LoaderSpec(loader=stage4_loader, requires_cycle=False, supports_graph=True)},
    )
    monkeypatch.setattr(
        bulk_cli,
        "resolve_stage4_committee_scope",
        MagicMock(return_value=None),
    )

    bulk_cli.dispatch_load(
        conn=fake_connection,
        config=bulk_cli.CliConfig(
            mode="single",
            cycle=2026,
            file_type="itcont",
            path=file_path,
            directory=None,
            batch_size=100,
            limit=None,
            graph_enabled=False,
            transactions_only=True,
            with_transactions=False,
        ),
        request=bulk_cli.LoadRequest(file_type="itcont", path=file_path),
        data_source_id=data_source_id,
    )

    assert len(captured_options) == 1
    assert captured_options[0].with_transactions is True
    assert captured_options[0].entity_extraction is False


@pytest.mark.unit
def test_validate_cli_arguments_requires_matching_mode_flags(tmp_path: Path) -> None:
    parser = bulk_cli.build_argument_parser()

    only_file_type = parser.parse_args(["--cycle", "2024", "--file-type", "cm"])
    only_path = parser.parse_args(["--cycle", "2024", "--path", str(tmp_path / "cm.txt")])
    mixed_modes = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(tmp_path / "cm.txt"),
            "--all",
            "--directory",
            str(tmp_path),
        ]
    )

    with pytest.raises(ValueError, match="single-file mode"):
        bulk_cli.validate_cli_arguments(only_file_type)
    with pytest.raises(ValueError, match="single-file mode"):
        bulk_cli.validate_cli_arguments(only_path)
    with pytest.raises(ValueError, match="mutually exclusive"):
        bulk_cli.validate_cli_arguments(mixed_modes)


@pytest.mark.unit
def test_validate_cli_arguments_requires_both_all_and_directory_for_full_mode(tmp_path: Path) -> None:
    parser = bulk_cli.build_argument_parser()
    only_all = parser.parse_args(["--cycle", "2024", "--all"])
    only_directory = parser.parse_args(["--cycle", "2024", "--directory", str(tmp_path)])

    with pytest.raises(ValueError, match="full-cycle mode requires both --all and --directory"):
        bulk_cli.validate_cli_arguments(only_all)
    with pytest.raises(ValueError, match="full-cycle mode requires both --all and --directory"):
        bulk_cli.validate_cli_arguments(only_directory)


@pytest.mark.unit
def test_validate_cli_arguments_rejects_non_positive_batch_size_and_limit(tmp_path: Path) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")
    parser = bulk_cli.build_argument_parser()

    bad_batch_size = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(file_path),
            "--batch-size",
            "0",
        ]
    )
    bad_limit = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(file_path),
            "--limit",
            "-1",
        ]
    )

    with pytest.raises(ValueError, match="batch_size"):
        bulk_cli.validate_cli_arguments(bad_batch_size)
    with pytest.raises(ValueError, match="limit"):
        bulk_cli.validate_cli_arguments(bad_limit)


@pytest.mark.unit
def test_validate_cli_arguments_rejects_missing_or_unreadable_paths(tmp_path: Path) -> None:
    parser = bulk_cli.build_argument_parser()
    missing_file = tmp_path / "missing_cm.txt"
    missing_directory = tmp_path / "missing_dir"

    single_args = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(missing_file),
        ]
    )
    full_cycle_args = parser.parse_args(
        [
            "--cycle",
            "2024",
            "--all",
            "--directory",
            str(missing_directory),
        ]
    )

    with pytest.raises(ValueError, match="readable file"):
        bulk_cli.validate_cli_arguments(single_args)
    with pytest.raises(ValueError, match="readable directory"):
        bulk_cli.validate_cli_arguments(full_cycle_args)


@pytest.mark.unit
def test_matches_file_type_accepts_zip_and_name_patterns() -> None:
    assert bulk_cli._matches_file_type(Path("cm24.ZIP"), "cm")
    assert bulk_cli._matches_file_type(Path("fec_2024_itcont.zip"), "itcont")
    assert bulk_cli._matches_file_type(Path("indiv24.zip"), "itcont")
    assert bulk_cli._matches_file_type(Path("pas224.zip"), "itpas2")
    assert bulk_cli._matches_file_type(Path("fec-2024-ccl.zip"), "ccl")
    assert not bulk_cli._matches_file_type(Path("cm24.csv"), "cm")


@pytest.mark.unit
def test_resolve_full_cycle_directory_requires_one_file_per_type(tmp_path: Path) -> None:
    (tmp_path / "cm_sample.txt").write_text("", encoding="latin-1")
    (tmp_path / "cm_2_sample.txt").write_text("", encoding="latin-1")

    with pytest.raises(ValueError, match="Ambiguous.*cm"):
        bulk_cli.resolve_full_cycle_directory(tmp_path)


@pytest.mark.unit
def test_resolve_full_cycle_directory_accepts_zip_files(tmp_path: Path) -> None:
    expected_paths: dict[str, Path] = {}
    for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
        path = tmp_path / f"{file_type}_sample.zip"
        path.write_text("", encoding="latin-1")
        expected_paths[file_type] = path

    resolved = bulk_cli.resolve_full_cycle_directory(tmp_path)

    assert resolved == expected_paths


@pytest.mark.unit
def test_resolve_full_cycle_directory_accepts_canonical_fec_download_filenames(tmp_path: Path) -> None:
    expected_paths = {
        "cm": tmp_path / "cm24.zip",
        "cn": tmp_path / "cn24.zip",
        "ccl": tmp_path / "ccl24.zip",
        "itcont": tmp_path / "indiv24.zip",
        "itpas2": tmp_path / "pas224.zip",
    }
    for path in expected_paths.values():
        path.write_text("", encoding="latin-1")

    resolved = bulk_cli.resolve_full_cycle_directory(tmp_path)

    assert resolved == expected_paths


@pytest.mark.unit
def test_resolve_full_cycle_directory_rejects_unreadable_matched_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
        (tmp_path / f"{file_type}_sample.txt").write_text("", encoding="latin-1")

    monkeypatch.setattr(
        bulk_cli,
        "_is_readable_file",
        lambda path: path.name != "itcont_sample.txt",
    )

    with pytest.raises(ValueError, match="Unreadable bulk file.*itcont"):
        bulk_cli.resolve_full_cycle_directory(tmp_path)


@pytest.mark.unit
def test_resolve_full_cycle_directory_rejects_file_reused_across_types(tmp_path: Path) -> None:
    (tmp_path / "cm_itcont_shared.txt").write_text("", encoding="latin-1")
    (tmp_path / "cn_sample.txt").write_text("", encoding="latin-1")
    (tmp_path / "ccl_sample.txt").write_text("", encoding="latin-1")
    (tmp_path / "itpas2_sample.txt").write_text("", encoding="latin-1")

    with pytest.raises(ValueError, match="matches multiple required file types: cm, itcont"):
        bulk_cli.resolve_full_cycle_directory(tmp_path)


@pytest.mark.unit
def test_dispatch_load_uses_stage3_and_stage4_loader_signatures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_source_id = uuid4()
    fake_connection = object()
    file_path = tmp_path / "cn_sample.txt"
    file_path.write_text("", encoding="latin-1")
    stage3_config = bulk_cli.CliConfig(
        mode="single",
        cycle=2024,
        file_type="cn",
        path=file_path,
        directory=None,
        batch_size=200,
        limit=5,
        graph_enabled=True,
    )
    stage4_config = bulk_cli.CliConfig(
        mode="single",
        cycle=2024,
        file_type="itcont",
        path=file_path,
        directory=None,
        batch_size=200,
        limit=7,
        graph_enabled=True,
        with_transactions=True,
    )
    weball_config = bulk_cli.CliConfig(
        mode="single",
        cycle=2024,
        file_type="weball",
        path=file_path,
        directory=None,
        batch_size=200,
        limit=9,
        graph_enabled=True,
    )
    committee_summary_config = bulk_cli.CliConfig(
        mode="single",
        cycle=2024,
        file_type="committee_summary",
        path=file_path,
        directory=None,
        batch_size=200,
        limit=11,
        graph_enabled=True,
    )

    stage3_loader = MagicMock(return_value=LoadResult(inserted=1, skipped=0, errors=0))
    stage4_loader = MagicMock(return_value=LoadResult(inserted=2, skipped=1, errors=0))
    weball_loader = MagicMock(return_value=LoadResult(inserted=3, skipped=0, errors=0))
    committee_summary_loader = MagicMock(return_value=LoadResult(inserted=4, skipped=0, errors=0))
    monkeypatch.setattr(
        bulk_cli,
        "FILE_TYPE_LOADERS",
        {
            "cn": bulk_cli.LoaderSpec(loader=stage3_loader, requires_cycle=True, supports_graph=False),
            "itcont": bulk_cli.LoaderSpec(loader=stage4_loader, requires_cycle=False, supports_graph=True),
            "weball": bulk_cli.LoaderSpec(loader=weball_loader, requires_cycle=True, supports_graph=False),
            "committee_summary": bulk_cli.LoaderSpec(
                loader=committee_summary_loader,
                requires_cycle=True,
                supports_graph=False,
            ),
        },
    )

    stage3_result = bulk_cli.dispatch_load(
        conn=fake_connection,
        config=stage3_config,
        request=bulk_cli.LoadRequest(file_type="cn", path=file_path),
        data_source_id=data_source_id,
    )
    stage4_result = bulk_cli.dispatch_load(
        conn=fake_connection,
        config=stage4_config,
        request=bulk_cli.LoadRequest(file_type="itcont", path=file_path),
        data_source_id=data_source_id,
    )
    weball_result = bulk_cli.dispatch_load(
        conn=fake_connection,
        config=weball_config,
        request=bulk_cli.LoadRequest(file_type="weball", path=file_path),
        data_source_id=data_source_id,
    )
    committee_summary_result = bulk_cli.dispatch_load(
        conn=fake_connection,
        config=committee_summary_config,
        request=bulk_cli.LoadRequest(file_type="committee_summary", path=file_path),
        data_source_id=data_source_id,
    )

    assert stage3_result == LoadResult(inserted=1, skipped=0, errors=0)
    assert stage4_result == LoadResult(inserted=2, skipped=1, errors=0)
    assert weball_result == LoadResult(inserted=3, skipped=0, errors=0)
    assert committee_summary_result == LoadResult(inserted=4, skipped=0, errors=0)
    stage3_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        batch_size=200,
        limit=5,
    )
    stage4_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        options=Stage4LoadOptions(
            batch_size=200,
            limit=7,
            graph_enabled=True,
            with_transactions=True,
        ),
    )
    weball_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        batch_size=200,
        limit=9,
    )
    committee_summary_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        batch_size=200,
        limit=11,
    )


@pytest.mark.unit
def test_dispatch_load_threads_count_only_through_stage4_filter_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_source_id = uuid4()
    fake_connection = object()
    file_path = tmp_path / "itcont_sample.txt"
    file_path.write_text("", encoding="latin-1")
    stage4_loader = MagicMock(return_value=LoadResult(inserted=7, skipped=3, errors=0))
    scoped_committees = frozenset({"C00000001", "C00000002"})
    monkeypatch.setattr(
        bulk_cli,
        "FILE_TYPE_LOADERS",
        {"itcont": bulk_cli.LoaderSpec(loader=stage4_loader, requires_cycle=False, supports_graph=True)},
    )
    monkeypatch.setattr(
        bulk_cli,
        "resolve_stage4_committee_scope",
        MagicMock(return_value=scoped_committees),
    )

    result = bulk_cli.dispatch_load(
        conn=fake_connection,
        config=bulk_cli.CliConfig(
            mode="single",
            cycle=2026,
            file_type="itcont",
            path=file_path,
            directory=None,
            batch_size=250,
            limit=5000,
            graph_enabled=True,
            transactions_only=True,
            spine_only=True,
            min_date=date(2022, 1, 1),
            count_only=True,
        ),
        request=bulk_cli.LoadRequest(file_type="itcont", path=file_path),
        data_source_id=data_source_id,
    )

    assert result == LoadResult(inserted=7, skipped=3, errors=0)
    bulk_cli.resolve_stage4_committee_scope.assert_called_once_with(fake_connection, spine_only=True)
    stage4_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2026,
        data_source_id=data_source_id,
        options=Stage4LoadOptions(
            batch_size=250,
            limit=5000,
            graph_enabled=True,
            with_transactions=True,
            entity_extraction=False,
            committee_fec_ids=scoped_committees,
            min_transaction_date=date(2022, 1, 1),
            count_only=True,
        ),
    )


@pytest.mark.unit
def test_dispatch_load_omits_limit_for_reference_files_in_full_cycle_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_source_id = uuid4()
    fake_connection = object()
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")
    full_config = bulk_cli.CliConfig(
        mode="full",
        cycle=2024,
        file_type=None,
        path=None,
        directory=tmp_path,
        batch_size=500,
        limit=50000,
        graph_enabled=False,
        canonical_stage4_resume_enabled=True,
    )

    cm_loader = MagicMock(return_value=LoadResult(inserted=10, skipped=0, errors=0))
    itcont_loader = MagicMock(return_value=LoadResult(inserted=5, skipped=0, errors=0))
    monkeypatch.setattr(
        bulk_cli,
        "FILE_TYPE_LOADERS",
        {
            "cm": bulk_cli.LoaderSpec(loader=cm_loader, requires_cycle=True, supports_graph=False),
            "itcont": bulk_cli.LoaderSpec(loader=itcont_loader, requires_cycle=False, supports_graph=True),
        },
    )

    bulk_cli.dispatch_load(
        conn=fake_connection,
        config=full_config,
        request=bulk_cli.LoadRequest(file_type="cm", path=file_path),
        data_source_id=data_source_id,
    )
    bulk_cli.dispatch_load(
        conn=fake_connection,
        config=full_config,
        request=bulk_cli.LoadRequest(file_type="itcont", path=file_path),
        data_source_id=data_source_id,
    )

    cm_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        batch_size=500,
        limit=None,
    )
    itcont_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        options=Stage4LoadOptions(
            batch_size=500,
            limit=50000,
            graph_enabled=False,
            with_transactions=False,
            canonical_resume_enabled=True,
        ),
    )


@pytest.mark.unit
def test_dispatch_load_keeps_noncanonical_full_cycle_helpers_off_shared_stage4_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_source_id = uuid4()
    fake_connection = object()
    file_path = tmp_path / "indiv24.zip"
    file_path.write_text("", encoding="latin-1")
    itcont_loader = MagicMock(return_value=LoadResult(inserted=5, skipped=0, errors=0))
    monkeypatch.setattr(
        bulk_cli,
        "FILE_TYPE_LOADERS",
        {"itcont": bulk_cli.LoaderSpec(loader=itcont_loader, requires_cycle=False, supports_graph=True)},
    )

    bulk_cli.dispatch_load(
        conn=fake_connection,
        config=bulk_cli.CliConfig(
            mode="full",
            cycle=2024,
            file_type=None,
            path=None,
            directory=tmp_path,
            batch_size=500,
            limit=50000,
            graph_enabled=False,
        ),
        request=bulk_cli.LoadRequest(file_type="itcont", path=file_path),
        data_source_id=data_source_id,
    )

    itcont_loader.assert_called_once_with(
        fake_connection,
        file_path,
        cycle=2024,
        data_source_id=data_source_id,
        options=Stage4LoadOptions(
            batch_size=500,
            limit=50000,
            graph_enabled=False,
            with_transactions=False,
        ),
    )


@pytest.mark.unit
def test_bootstrap_connection_applies_graph_hooks_conditionally(monkeypatch: pytest.MonkeyPatch) -> None:
    graph_connection = _build_connection()
    plain_connection = _build_connection()
    get_connection = MagicMock(side_effect=[graph_connection, plain_connection])
    ensure_graph = MagicMock()

    monkeypatch.setattr(bulk_cli, "get_connection", get_connection)
    monkeypatch.setattr(bulk_cli, "ensure_graph", ensure_graph)

    assert bulk_cli.bootstrap_connection(graph_enabled=True) is graph_connection
    assert bulk_cli.bootstrap_connection(graph_enabled=False) is plain_connection

    assert get_connection.call_args_list[0].kwargs == {"post_connect": bulk_cli.age_post_connect}
    assert get_connection.call_args_list[1].kwargs == {"post_connect": None}
    ensure_graph.assert_called_once_with(graph_connection)
    graph_connection.commit.assert_called_once_with()
    plain_connection.commit.assert_not_called()


@pytest.mark.unit
def test_bootstrap_connection_closes_connection_when_graph_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_connection = _build_connection()

    monkeypatch.setattr(bulk_cli, "get_connection", MagicMock(return_value=graph_connection))
    monkeypatch.setattr(bulk_cli, "ensure_graph", MagicMock(side_effect=RuntimeError("graph bootstrap failed")))

    with pytest.raises(RuntimeError, match="graph bootstrap failed"):
        bulk_cli.bootstrap_connection(graph_enabled=True)

    graph_connection.close.assert_called_once_with()
    graph_connection.commit.assert_not_called()


@pytest.mark.unit
def test_print_summary_outputs_file_rows_and_totals(capsys: pytest.CaptureFixture) -> None:
    summaries = [
        bulk_cli.LoadStepSummary(
            file_type="cm",
            source_path=Path("/tmp/cm_sample.txt"),
            result=LoadResult(inserted=2, skipped=1, errors=0),
            elapsed_seconds=0.55,
        ),
        bulk_cli.LoadStepSummary(
            file_type="cn",
            source_path=Path("/tmp/cn_sample.txt"),
            result=LoadResult(inserted=3, skipped=0, errors=1),
            elapsed_seconds=0.25,
        ),
    ]

    bulk_cli.print_summary(summaries)
    captured = capsys.readouterr()

    assert "file_type" in captured.out
    assert "cm" in captured.out
    assert "cn" in captured.out
    assert "Totals" in captured.out
    assert "inserted=5" in captured.out
    assert "skipped=1" in captured.out
    assert "errors=1" in captured.out


@pytest.mark.unit
def test_main_returns_non_zero_on_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")

    bootstrap_connection = MagicMock()
    monkeypatch.setattr(bulk_cli, "bootstrap_connection", bootstrap_connection)

    exit_code = bulk_cli.main(["--cycle", "2024", "--file-type", "cm"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "validation failed" in captured.err
    bootstrap_connection.assert_not_called()


@pytest.mark.unit
def test_main_success_single_file_prints_summary_and_returns_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")
    connection = _build_connection()

    monkeypatch.setattr(bulk_cli, "bootstrap_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(bulk_cli, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    finalize_full_cycle_metadata = MagicMock()
    monkeypatch.setattr(bulk_cli, "finalize_full_cycle_metadata", finalize_full_cycle_metadata)
    monkeypatch.setattr(
        bulk_cli,
        "dispatch_load",
        MagicMock(return_value=LoadResult(inserted=4, skipped=1, errors=0)),
    )

    exit_code = bulk_cli.main(
        [
            "--cycle",
            "2024",
            "--file-type",
            "cm",
            "--path",
            str(file_path),
            "--batch-size",
            "25",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Totals" in captured.out
    assert "inserted=4" in captured.out
    connection.close.assert_called_once()
    finalize_full_cycle_metadata.assert_not_called()


@pytest.mark.unit
def test_main_count_only_skips_data_source_bootstrap_and_reports_no_write_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    file_path = tmp_path / "itcont_sample.txt"
    file_path.write_text("", encoding="latin-1")
    connection = _build_connection()

    monkeypatch.setattr(bulk_cli, "bootstrap_connection", MagicMock(return_value=connection))
    ensure_fec_bulk_data_source = MagicMock(return_value=uuid4())
    monkeypatch.setattr(bulk_cli, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(
        bulk_cli,
        "dispatch_load",
        MagicMock(return_value=LoadResult(inserted=7, skipped=2, errors=0)),
    )

    exit_code = bulk_cli.main(
        [
            "--cycle",
            "2026",
            "--file-type",
            "itcont",
            "--path",
            str(file_path),
            "--count-only",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "no database writes were performed" in captured.out
    ensure_fec_bulk_data_source.assert_not_called()


@pytest.mark.unit
def test_main_success_full_cycle_syncs_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
        (tmp_path / f"{file_type}_sample.txt").write_text("", encoding="latin-1")

    connection = _build_connection()
    data_source_id = uuid4()
    summaries = [
        bulk_cli.LoadStepSummary(
            file_type="cm",
            source_path=tmp_path / "cm_sample.txt",
            result=LoadResult(inserted=2, skipped=0, errors=0),
            elapsed_seconds=0.1,
        ),
        bulk_cli.LoadStepSummary(
            file_type="itcont",
            source_path=tmp_path / "itcont_sample.txt",
            result=LoadResult(inserted=0, skipped=3, errors=1),
            elapsed_seconds=0.2,
        ),
    ]
    finalize_full_cycle_metadata = MagicMock(
        return_value=bulk_cli.FullCycleFinalizationOutcome(
            pull_status="partial",
            record_count=42,
        )
    )

    monkeypatch.setattr(bulk_cli, "bootstrap_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(bulk_cli, "ensure_fec_bulk_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(bulk_cli, "load_full_cycle", MagicMock(return_value=summaries))
    monkeypatch.setattr(bulk_cli, "finalize_full_cycle_metadata", finalize_full_cycle_metadata)

    exit_code = bulk_cli.main(["--cycle", "2024", "--all", "--directory", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Totals" in captured.out
    finalize_full_cycle_metadata.assert_called_once_with(connection, data_source_id, summaries)
    connection.close.assert_called_once()


@pytest.mark.unit
def test_main_returns_one_when_full_cycle_setup_fails_before_db_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    bootstrap_connection = MagicMock()
    monkeypatch.setattr(bulk_cli, "bootstrap_connection", bootstrap_connection)

    exit_code = bulk_cli.main(["--cycle", "2024", "--all", "--directory", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Bulk ingest setup failed" in captured.err
    bootstrap_connection.assert_not_called()


@pytest.mark.unit
def test_main_reports_phase_name_on_orchestrator_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")
    connection = _build_connection()

    monkeypatch.setattr(bulk_cli, "bootstrap_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(bulk_cli, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(bulk_cli, "dispatch_load", MagicMock(side_effect=RuntimeError("cm phase exploded")))

    exit_code = bulk_cli.main(["--cycle", "2024", "--file-type", "cm", "--path", str(file_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "cm" in captured.err
    connection.close.assert_called_once()


@pytest.mark.unit
def test_main_wraps_single_file_loader_failures_with_phase_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    file_path = tmp_path / "cm_sample.txt"
    file_path.write_text("", encoding="latin-1")
    connection = _build_connection()

    monkeypatch.setattr(bulk_cli, "bootstrap_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(bulk_cli, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(bulk_cli, "dispatch_load", MagicMock(side_effect=RuntimeError("database exploded")))

    exit_code = bulk_cli.main(["--cycle", "2024", "--file-type", "cm", "--path", str(file_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "cm phase failed" in captured.err
    assert str(file_path) in captured.err
    connection.close.assert_called_once()
