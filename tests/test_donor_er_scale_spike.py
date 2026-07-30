from __future__ import annotations

import hashlib
import importlib
import inspect
import argparse
import os
import socket
import subprocess
import sys
import tomllib
import zipfile
import json
from pathlib import Path
from typing import Any, get_type_hints
from uuid import UUID

import pytest
from pydantic import ValidationError

from tests.test_debbie_post_sync_hook import project_debbie_public_mirror

REPO_ROOT = Path(__file__).resolve().parents[1]

MATERIALIZE_ARGUMENTS = [
    "materialize",
    "--data-root",
    "data",
    "--committee-id-file",
    "committee_ids.txt",
    "--expected-committee-count",
    "2",
    "--committee-id-file-sha256",
    "0" * 64,
    "--archive-url",
    "https://example.invalid/indiv26.zip",
    "--archive-member-name",
    "itcont.txt",
    "--archive-sha256",
    "1" * 64,
    "--archive-size-bytes",
    "100",
    "--output-path",
    "normalized_rows.jsonl",
    "--cohort-size",
    "10",
    "--timeout-seconds",
    "30",
    "--memory-bytes",
    "1048576",
    "--temp-bytes",
    "1048576",
    "--temp-root",
    "tmp",
]
MATERIALIZE_REQUIRED_OPTIONS = (
    "--data-root",
    "--committee-id-file",
    "--expected-committee-count",
    "--committee-id-file-sha256",
    "--archive-url",
    "--archive-member-name",
    "--archive-sha256",
    "--archive-size-bytes",
    "--output-path",
    "--cohort-size",
    "--timeout-seconds",
    "--memory-bytes",
    "--temp-bytes",
    "--temp-root",
)
BENCHMARK_ARGUMENTS = [
    "benchmark",
    "--input-path",
    "normalized_rows.jsonl",
    "--output-path",
    "receipt.json",
    "--cohort-size",
    "10",
    "--timeout-seconds",
    "30",
    "--memory-bytes",
    "1048576",
    "--temp-bytes",
    "1048576",
    "--temp-root",
    "tmp",
]
BENCHMARK_REQUIRED_OPTIONS = (
    "--input-path",
    "--output-path",
    "--cohort-size",
    "--timeout-seconds",
    "--memory-bytes",
    "--temp-bytes",
    "--temp-root",
)
DONOR_PROXY_ARGUMENTS = [
    "donor-proxy",
    "--committee-id",
    "00000000-0000-0000-0000-000000000001",
    "--committee-id",
    "00000000-0000-0000-0000-000000000002",
    "--slice-size",
    "125",
    "--cluster-sample-size",
    "2",
    "--seed",
    "stage-2-seed",
    "--output-path",
    "donor_proxy_receipt.md",
    "--timeout-seconds",
    "30",
    "--memory-bytes",
    "1048576",
    "--temp-bytes",
    "1048576",
    "--temp-root",
    "tmp",
]
DONOR_PROXY_REQUIRED_OPTIONS = (
    "--committee-id",
    "--slice-size",
    "--cluster-sample-size",
    "--seed",
    "--output-path",
    "--timeout-seconds",
    "--memory-bytes",
    "--temp-bytes",
    "--temp-root",
)


def _load_harness() -> Any:
    return importlib.import_module("scripts.donor_er_scale_spike")


def _subcommand_choices(parser: Any) -> set[str]:
    for action in parser._actions:
        if getattr(action, "choices", None):
            return set(action.choices)
    raise AssertionError("parser must define subcommands")


def _without_option(argv: list[str], option: str) -> list[str]:
    stripped: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == option:
            index += 2
            continue
        stripped.append(argv[index])
        index += 1
    return stripped


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_committee_file(path: Path, committee_ids: list[str]) -> None:
    path.write_text("\n".join(committee_ids) + "\n", encoding="utf-8")


def _write_itcont_zip(path: Path, *, member_name: str = "itcont.txt", rows: list[str] | None = None) -> None:
    payload_rows = rows or [
        "C00100001|N|Q1|P|1|15|IND|DOE, JANE|RALEIGH|NC|276011234|ACME|ENGINEER|01012024|25.00||T1|1|||9001"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member_name, "\n".join(payload_rows) + "\n")


def _itcont_row(
    *,
    committee_id: str = "C00100001",
    amendment: str = "N",
    transaction_type: str = "15",
    entity_type: str = "IND",
    name: str = "DOE, JANE",
    city: str = "RALEIGH",
    state: str = "NC",
    zip_code: str = "276011234",
    employer: str = "ACME",
    occupation: str = "ENGINEER",
    date: str = "01012024",
    memo_code: str = "",
    sub_id: str = "9001",
) -> str:
    return "|".join(
        [
            committee_id,
            amendment,
            "Q1",
            "P",
            "1",
            transaction_type,
            entity_type,
            name,
            city,
            state,
            zip_code,
            employer,
            occupation,
            date,
            "25.00",
            "",
            f"T{sub_id}",
            "1",
            memo_code,
            "",
            sub_id,
        ]
    )


def _materialized_json_rows(path: Path, harness: Any) -> list[Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [harness.NormalizedBenchmarkRow.model_validate_json(line) for line in lines if line]


def _materialize_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    harness = _load_harness()
    data_root = tmp_path / "data"
    temp_root = tmp_path / "lane"
    data_root.mkdir(exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    committee_file = temp_root / "committee_ids.txt"
    if not committee_file.exists():
        _write_committee_file(committee_file, ["C00100001", "C00100002"])
    archive_path = data_root / "indiv26.zip"
    if not archive_path.exists():
        _write_itcont_zip(archive_path)
    values: dict[str, object] = {
        "data_root": str(data_root),
        "committee_id_file": str(committee_file),
        "expected_committee_count": 2,
        "committee_id_file_sha256": _sha256_file(committee_file),
        "archive_url": str(archive_path),
        "archive_member_name": "itcont.txt",
        "archive_sha256": _sha256_file(archive_path),
        "archive_size_bytes": archive_path.stat().st_size,
        "output_path": str(temp_root / "normalized_rows.jsonl"),
        "cohort_size": 10,
        "timeout_seconds": 30,
        "memory_bytes": 64 * 1024 * 1024,
        "temp_bytes": 64 * 1024 * 1024,
        "temp_root": str(temp_root),
        "func": harness._materialize,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _benchmark_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {
        "input_path": str(temp_root / "normalized_rows.jsonl"),
        "output_path": str(temp_root / "receipt.json"),
        "cohort_size": 10,
        "timeout_seconds": 30,
        "memory_bytes": 64 * 1024 * 1024,
        "temp_bytes": 64 * 1024 * 1024,
        "temp_root": str(temp_root),
        "func": harness._benchmark,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _benchmark_child_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    return _benchmark_args(tmp_path, _run_in_process=True, **overrides)


def _donor_proxy_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {
        "committee_ids": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "slice_size": 125,
        "cluster_sample_size": 2,
        "seed": "stage-2-seed",
        "output_path": str(temp_root / "donor_proxy_receipt.md"),
        "timeout_seconds": 30,
        "memory_bytes": 64 * 1024 * 1024,
        "temp_bytes": 64 * 1024 * 1024,
        "temp_root": str(temp_root),
        "func": harness._donor_proxy,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _passed_benchmark_receipt(
    harness: Any,
    args: argparse.Namespace,
    *,
    benchmark_invocation_id: str = "stale-invocation",
) -> Any:
    input_sha256 = hashlib.sha256(Path(args.input_path).read_bytes()).hexdigest()
    observation = harness.RunObservation(
        command="benchmark",
        input_rows=0,
        output_rows=1,
        cohort_size=args.cohort_size,
        timeout_seconds=args.timeout_seconds,
        memory_bytes=args.memory_bytes,
        temp_bytes=args.temp_bytes,
        temp_root=str(Path(args.temp_root).resolve()),
        input_sha256=input_sha256,
        unique_signature_count=0,
        null_counts={field: 0 for field in ("canonical_name", "employer", "occupation", "city", "state", "zip5")},
        blocking_rules=[],
        max_block_size=0,
        elapsed_seconds=0.01,
        peak_rss_bytes=0,
        peak_temp_bytes=0,
        exit_state="passed",
        benchmark_invocation_id=benchmark_invocation_id,
    )
    return harness.DonorErScaleSpikeReceipt(
        schema_version="donor_er_scale_spike.v1",
        rows_sha256=input_sha256,
        observations=(observation,),
    )


def _benchmark_invocation_id_from_child_argv(argv: list[str]) -> str:
    return argv[argv.index("--benchmark-invocation-id") + 1]


def _write_normalized_jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(f"{row.model_dump_json()}\n" for row in rows), encoding="utf-8")


def test_public_module_surface_and_cli_subcommands() -> None:
    harness = _load_harness()

    main_signature = inspect.signature(harness.main)
    type_hints = get_type_hints(harness.main)
    assert list(main_signature.parameters) == ["argv"]
    assert main_signature.parameters["argv"].default is None
    assert type_hints == {"argv": list[str] | None, "return": int}
    parser = harness.build_argument_parser()
    assert _subcommand_choices(parser) == {"materialize", "benchmark", "donor-proxy", "validate-receipt"}


@pytest.mark.parametrize(
    ("complete_argv", "missing_option"),
    [
        *((MATERIALIZE_ARGUMENTS, option) for option in MATERIALIZE_REQUIRED_OPTIONS),
        *((BENCHMARK_ARGUMENTS, option) for option in BENCHMARK_REQUIRED_OPTIONS),
        *((DONOR_PROXY_ARGUMENTS, option) for option in DONOR_PROXY_REQUIRED_OPTIONS),
    ],
    ids=[
        option for option in (*MATERIALIZE_REQUIRED_OPTIONS, *BENCHMARK_REQUIRED_OPTIONS, *DONOR_PROXY_REQUIRED_OPTIONS)
    ],
)
def test_each_cli_required_evidence_option_exits_nonzero_before_work_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    complete_argv: list[str],
    missing_option: str,
) -> None:
    harness = _load_harness()

    def fail_if_called(_args: Any) -> int:
        raise AssertionError("runtime work must not run when required evidence is missing")

    monkeypatch.setattr(harness, "_materialize", fail_if_called)
    monkeypatch.setattr(harness, "_benchmark", fail_if_called)
    monkeypatch.setattr(harness, "_donor_proxy", fail_if_called)

    assert harness.main(_without_option(complete_argv, missing_option)) != 0


def test_durable_models_forbid_unknown_fields_and_dump_stable_json() -> None:
    harness = _load_harness()
    row = harness.NormalizedBenchmarkRow(
        row_id="a" * 64,
        canonical_name="JANE Q DOE",
        employer=None,
        occupation="Engineer",
        city="RALEIGH",
        state="NC",
        zip5="27601",
    )
    observation = harness.RunObservation(
        command="benchmark",
        input_rows=1,
        output_rows=1,
        cohort_size=1,
        timeout_seconds=30,
        memory_bytes=1048576,
        temp_bytes=1048576,
        temp_root="/tmp/civibus",
        input_sha256="c" * 64,
        unique_signature_count=1,
        null_counts={
            "canonical_name": 0,
            "employer": 1,
            "occupation": 0,
            "city": 0,
            "state": 0,
            "zip5": 0,
        },
        blocking_rules=[
            {
                "rule_index": 0,
                "blocking_rule": "l.last_name = r.last_name",
                "exclusive_pair_count": 0,
                "cumulative_pair_count": 0,
                "max_block_size": 0,
            }
        ],
        max_block_size=0,
        elapsed_seconds=0.01,
        peak_rss_bytes=0,
        peak_temp_bytes=0,
        exit_state="passed",
        benchmark_invocation_id="test-invocation",
    )
    receipt = harness.DonorErScaleSpikeReceipt(
        schema_version="donor_er_scale_spike.v1",
        rows_sha256="b" * 64,
        observations=(observation,),
    )

    assert row.model_config["extra"] == "forbid"
    assert observation.model_config["extra"] == "forbid"
    assert receipt.model_config["extra"] == "forbid"
    assert row.model_dump_json() == (
        '{"row_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"canonical_name":"JANE Q DOE","employer":null,"occupation":"Engineer",'
        '"city":"RALEIGH","state":"NC","zip5":"27601"}'
    )
    assert receipt.model_dump_json() == (
        '{"schema_version":"donor_er_scale_spike.v1",'
        '"rows_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        '"observations":[{"command":"benchmark","input_rows":1,"output_rows":1,'
        '"cohort_size":1,"timeout_seconds":30,"memory_bytes":1048576,'
        '"temp_bytes":1048576,"temp_root":"/tmp/civibus",'
        '"input_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
        '"unique_signature_count":1,'
        '"null_counts":{"canonical_name":0,"employer":1,"occupation":0,"city":0,"state":0,"zip5":0},'
        '"blocking_rules":[{"rule_index":0,"blocking_rule":"l.last_name = r.last_name",'
        '"exclusive_pair_count":0,"cumulative_pair_count":0,"max_block_size":0}],'
        '"max_block_size":0,"elapsed_seconds":0.01,"peak_rss_bytes":0,'
        '"peak_temp_bytes":0,"exit_state":"passed","benchmark_invocation_id":"test-invocation"}]}'
    )

    with pytest.raises(ValidationError):
        harness.NormalizedBenchmarkRow(
            row_id="a" * 64,
            canonical_name="JANE Q DOE",
            employer=None,
            occupation="Engineer",
            city="RALEIGH",
            state="NC",
            zip5="27601",
            donor_key="forbidden",
        )

    with pytest.raises(ValidationError, match="missing required evidence"):
        harness.RunObservation(
            command="benchmark",
            input_rows=1,
            output_rows=1,
            cohort_size=1,
            timeout_seconds=30,
            memory_bytes=1048576,
            temp_bytes=1048576,
            temp_root="/tmp/civibus",
        )


# Independent expected literal lists, kept in the test only to prove the closed
# contract the harness schema owns once.
EXPECTED_B2_DISPOSITIONS = {"GO", "NO_GO"}
EXPECTED_B2_BLOCKER_CLASSES = {"NONE", "COVERAGE_IDENTITY", "CAPACITY", "EXTERNAL_EVIDENCE", "UNCLASSIFIED"}
EXPECTED_UNCLASSIFIED_REASONS = {
    "CONFLICTING_SOURCE_EVIDENCE",
    "INSUFFICIENT_SOURCE_EVIDENCE",
}
EXPECTED_ARCHITECTURE_DISPOSITIONS = {
    "ADOPT_BOUNDED_SINGLE_NODE",
    "ADOPT_PARTITIONED_BLOCKING",
    "ADOPT_EXTERNAL_ER_SERVICE",
}
EXPECTED_TERMINAL_DISPOSITIONS = EXPECTED_ARCHITECTURE_DISPOSITIONS | {"MEASUREMENT_NOT_READY"}
NO_GO_BLOCKER_CLASSES = sorted(EXPECTED_B2_BLOCKER_CLASSES - {"NONE"})


def _passing_benchmark_receipt(harness: Any) -> Any:
    observation = harness.RunObservation(
        command="benchmark",
        input_rows=1,
        output_rows=1,
        cohort_size=1,
        timeout_seconds=30,
        memory_bytes=1048576,
        temp_bytes=1048576,
        temp_root="/tmp/lane",
        input_sha256="c" * 64,
        unique_signature_count=1,
        null_counts={field: 0 for field in ("canonical_name", "employer", "occupation", "city", "state", "zip5")},
        blocking_rules=[
            {
                "rule_index": 0,
                "blocking_rule": "l.last_name = r.last_name",
                "exclusive_pair_count": 1,
                "cumulative_pair_count": 1,
                "max_block_size": 1,
            }
        ],
        max_block_size=1,
        elapsed_seconds=0.01,
        peak_rss_bytes=1,
        peak_temp_bytes=1,
        exit_state="passed",
        benchmark_invocation_id="inv",
    )
    return harness.DonorErScaleSpikeReceipt(
        schema_version="donor_er_scale_spike.v1",
        rows_sha256="d" * 64,
        observations=(observation,),
    )


def _resource_locality_kwargs() -> dict[str, object]:
    return {
        "execution_locality": "local_colima_worktree",
        "offline": True,
        "peak_rss_bytes": 1024,
        "peak_temp_bytes": 2048,
        "memory_budget_bytes": 1048576,
        "temp_budget_bytes": 1048576,
    }


def _cleanup_kwargs() -> dict[str, object]:
    return {
        "data_root_path": "/tmp/lane/data",
        "data_root_created": True,
        "data_root_removed": True,
        "temp_root_path": "/tmp/lane/tmp",
        "temp_root_created": True,
        "temp_root_removed": True,
        "credential_root_path": "/tmp/lane/credentials",
        "credential_root_absent": True,
        "credential_paths": [],
        "credential_files_present": 0,
        "lane_pid_count": 0,
        "lane_proxy_count": 0,
    }


def _go_receipt_kwargs(harness: Any, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "schema_version": "donor_er_architecture_receipt.v1",
        "b2_disposition": "GO",
        "b2_blocker_class": "NONE",
        "terminal_disposition": "ADOPT_BOUNDED_SINGLE_NODE",
        "materialization_started": True,
        "b2_source": {
            "verbatim_verdict": "B2: GO — donor ER measurement cleared",
            "source_path": "core/refresh/job_builders.py",
        },
        "archive_identities": [_archive_identity_kwargs()],
        "resource_locality": _resource_locality_kwargs(),
        "cleanup_evidence": _cleanup_kwargs(),
        "benchmark": _passing_benchmark_receipt(harness),
        "blocker_evidence": None,
    }
    kwargs.update(overrides)
    return kwargs


def _no_go_receipt_kwargs(harness: Any, blocker_class: str = "CAPACITY", **overrides: object) -> dict[str, object]:
    source_evidence = "B2 log: bounded temp spill exceeded budget at cohort scale"
    detail = "capacity blocker: temp spill exceeded the requested byte budget"
    if blocker_class == "UNCLASSIFIED":
        source_evidence = "B2 source wording is insufficient to map deterministically"
        detail = "normalization re-gate required"
    kwargs = _go_receipt_kwargs(
        harness,
        b2_disposition="NO_GO",
        b2_blocker_class=blocker_class,
        terminal_disposition="MEASUREMENT_NOT_READY",
        # A NO-GO receipt is terminal not-ready: nothing materialized, so it
        # carries the decision menu instead of benchmark observations.
        materialization_started=False,
        decision_menu=_decision_menu_kwargs(),
        b2_source={
            "verbatim_verdict": "B2: NO-GO — bounded temp budget exceeded",
            "source_path": "core/refresh/job_builders.py",
        },
        benchmark=None,
        blocker_evidence={
            "normalized_owner_path": "core/entity_resolution/splink_runtime.py",
            "source_evidence": source_evidence,
            "normalization_reason": ("INSUFFICIENT_SOURCE_EVIDENCE" if blocker_class == "UNCLASSIFIED" else None),
            "rerun_command": "uv run --extra dev --extra entity-resolution scripts/donor_er_scale_spike.py benchmark",
            "detail": detail,
        },
    )
    kwargs.update(overrides)
    return kwargs


def _receipt_payload(harness: Any, kwargs: dict[str, object]) -> dict[str, Any]:
    return json.loads(harness.DonorErArchitectureReceipt(**kwargs).model_dump_json())


def _receipt_markdown(receipt_json: str, *, language: str = "donor_er_scale_spike_receipt") -> str:
    return f"```{language}\n{receipt_json}\n```\n"


def _receipt_markdown_with_narrative(receipt_json: str, *, language: str = "donor_er_scale_spike_receipt") -> str:
    return (
        "# D2 architecture receipt\n\n"
        "Narrative that loosely mentions GO and NO_GO and ADOPT_BOUNDED_SINGLE_NODE "
        'and even a fake `{"b2_disposition": "GO"}` object outside any fence.\n\n'
        f"```{language}\n{receipt_json}\n```\n\nTrailing prose.\n"
    )


def test_architecture_receipt_owns_closed_literal_sets() -> None:
    harness = _load_harness()
    assert {"b2_disposition", "b2_blocker_class", "terminal_disposition"} <= set(
        harness.DonorErArchitectureReceipt.model_fields
    )
    assert harness.B2_DISPOSITIONS == EXPECTED_B2_DISPOSITIONS
    assert harness.B2_BLOCKER_CLASSES == EXPECTED_B2_BLOCKER_CLASSES
    assert harness.ARCHITECTURE_DISPOSITIONS == EXPECTED_ARCHITECTURE_DISPOSITIONS
    assert harness.TERMINAL_DISPOSITIONS == EXPECTED_TERMINAL_DISPOSITIONS


def test_architecture_receipt_forbids_unknown_fields_and_exposes_disposition_fields() -> None:
    harness = _load_harness()
    receipt = harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness))

    assert receipt.model_config["extra"] == "forbid"
    assert receipt.b2_source.model_config["extra"] == "forbid"
    assert receipt.cleanup_evidence.model_config["extra"] == "forbid"
    assert receipt.resource_locality.model_config["extra"] == "forbid"
    payload = json.loads(receipt.model_dump_json())
    assert payload["b2_disposition"] == "GO"
    assert payload["b2_blocker_class"] == "NONE"
    assert payload["terminal_disposition"] == "ADOPT_BOUNDED_SINGLE_NODE"
    # Round-trips cleanly: dump then reload survives extra="forbid".
    assert harness.DonorErArchitectureReceipt.model_validate_json(receipt.model_dump_json()) == receipt

    with pytest.raises(ValidationError):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, unexpected="forbidden"))
    with pytest.raises(ValidationError):
        nested = _go_receipt_kwargs(harness)
        nested["b2_source"] = {**nested["b2_source"], "leaked_env": "PGPASSWORD=x"}  # type: ignore[dict-item]
        harness.DonorErArchitectureReceipt(**nested)


@pytest.mark.parametrize("blocker_class", sorted(EXPECTED_B2_BLOCKER_CLASSES))
def test_architecture_receipt_blocker_class_go_no_go_invariants(blocker_class: str) -> None:
    harness = _load_harness()

    if blocker_class == "NONE":
        assert harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness)).b2_blocker_class == "NONE"
        # B2 GO forbids any non-NONE class.
        with pytest.raises(ValidationError, match="b2_blocker_class NONE"):
            harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, b2_blocker_class="CAPACITY"))
        # B2 GO forbids blocker details.
        with pytest.raises(ValidationError, match="forbids blocker evidence"):
            harness.DonorErArchitectureReceipt(
                **_go_receipt_kwargs(
                    harness,
                    blocker_evidence={
                        "normalized_owner_path": "core/x.py",
                        "source_evidence": "e",
                        "normalization_reason": None,
                        "rerun_command": "cmd",
                        "detail": "d",
                    },
                )
            )
        return

    assert harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, blocker_class)).b2_blocker_class == (
        blocker_class
    )
    # B2 NO-GO forbids NONE.
    with pytest.raises(ValidationError, match="forbids b2_blocker_class NONE"):
        harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, "NONE"))
    # B2 NO-GO requires blocker evidence with nonblank owner path, source, and rerun command.
    with pytest.raises(ValidationError, match="requires blocker evidence"):
        harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, blocker_class, blocker_evidence=None))
    for blank_field in ("normalized_owner_path", "source_evidence", "rerun_command"):
        kwargs = _no_go_receipt_kwargs(harness, blocker_class)
        kwargs["blocker_evidence"] = {**kwargs["blocker_evidence"], blank_field: "   "}  # type: ignore[dict-item]
        with pytest.raises(ValidationError, match="nonblank"):
            harness.DonorErArchitectureReceipt(**kwargs)


def test_architecture_receipt_terminal_disposition_rules() -> None:
    harness = _load_harness()
    # Name every allowed architecture-disposition literal locally, then prove they
    # are accepted only for a GO whose measurement cleared.
    for architecture_disposition in sorted(EXPECTED_ARCHITECTURE_DISPOSITIONS):
        receipt = harness.DonorErArchitectureReceipt(
            **_go_receipt_kwargs(harness, terminal_disposition=architecture_disposition)
        )
        assert receipt.terminal_disposition == architecture_disposition
        assert receipt.requires_normalization_regate is False
        # An architecture disposition is never valid for a NO-GO.
        with pytest.raises(ValidationError, match="MEASUREMENT_NOT_READY"):
            harness.DonorErArchitectureReceipt(
                **_no_go_receipt_kwargs(harness, "CAPACITY", terminal_disposition=architecture_disposition)
            )

    # GO forbids the not-ready terminal; NO-GO requires it.
    with pytest.raises(ValidationError, match="architecture terminal_disposition"):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, terminal_disposition="MEASUREMENT_NOT_READY"))
    assert (
        harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, "CAPACITY")).terminal_disposition
        == "MEASUREMENT_NOT_READY"
    )

    # UNCLASSIFIED is valid only for a NO-GO and forces the normalization re-gate.
    unclassified = harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, "UNCLASSIFIED"))
    assert unclassified.terminal_disposition == "MEASUREMENT_NOT_READY"
    assert unclassified.requires_normalization_regate is True
    assert (
        harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, "CAPACITY")).requires_normalization_regate
        is False
    )

    # Unknown disposition literals are rejected outright.
    with pytest.raises(ValidationError):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, terminal_disposition="ADOPT_MYSTERY"))
    with pytest.raises(ValidationError):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, b2_disposition="MAYBE"))


def test_architecture_receipt_unclassified_uses_closed_reason_and_preserves_source_evidence() -> None:
    harness = _load_harness()

    assert harness.UNCLASSIFIED_REASONS == EXPECTED_UNCLASSIFIED_REASONS
    for normalization_reason, source_evidence in (
        ("CONFLICTING_SOURCE_EVIDENCE", "B2 sources are conflicting and cannot be mapped deterministically"),
        ("INSUFFICIENT_SOURCE_EVIDENCE", "B2 source wording is insufficient to map deterministically"),
    ):
        blocker_evidence = {
            **_no_go_receipt_kwargs(harness, "UNCLASSIFIED")["blocker_evidence"],
            "source_evidence": source_evidence,
            "normalization_reason": normalization_reason,
        }
        receipt = harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(harness, "UNCLASSIFIED", blocker_evidence=blocker_evidence)
        )
        assert receipt.requires_normalization_regate is True
        assert receipt.blocker_evidence.source_evidence == source_evidence
        assert receipt.blocker_evidence.normalization_reason == normalization_reason

    unknown_reason_evidence = {
        **_no_go_receipt_kwargs(harness, "UNCLASSIFIED")["blocker_evidence"],
        "normalization_reason": "AMBIGUOUS_SOURCE_EVIDENCE",
    }
    with pytest.raises(ValidationError):
        harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(harness, "UNCLASSIFIED", blocker_evidence=unknown_reason_evidence)
        )

    classified_reason_evidence = {
        **_no_go_receipt_kwargs(harness, "CAPACITY")["blocker_evidence"],
        "normalization_reason": "INSUFFICIENT_SOURCE_EVIDENCE",
    }
    with pytest.raises(ValidationError, match="valid only for UNCLASSIFIED"):
        harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(harness, "CAPACITY", blocker_evidence=classified_reason_evidence)
        )

    deterministic_capacity_evidence = {
        **_no_go_receipt_kwargs(harness, "UNCLASSIFIED")["blocker_evidence"],
        "source_evidence": "B2 proves deterministic capacity; not insufficient or conflicting",
        "normalization_reason": None,
    }
    with pytest.raises(ValidationError, match="closed normalization_reason"):
        harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(
                harness,
                "UNCLASSIFIED",
                blocker_evidence=deterministic_capacity_evidence,
            )
        )


def test_architecture_receipt_disposition_conditional_benchmark_observations() -> None:
    harness = _load_harness()
    # GO requires a passed benchmark receipt.
    with pytest.raises(ValidationError, match="passed benchmark receipt"):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, benchmark=None))
    failed = _passing_benchmark_receipt(harness)
    failed_observation = failed.observations[0].model_copy(update={"exit_state": "failed"})
    failed = failed.model_copy(update={"observations": (failed_observation,)})
    with pytest.raises(ValidationError, match="passed benchmark receipt"):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, benchmark=failed))
    # NO-GO must not carry benchmark observations.
    with pytest.raises(ValidationError, match="must not carry benchmark observations"):
        harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(harness, "CAPACITY", benchmark=_passing_benchmark_receipt(harness))
        )

    non_benchmark_observation = harness.RunObservation(
        command="materialize",
        input_rows=1,
        output_rows=1,
        cohort_size=1,
        timeout_seconds=30,
        memory_bytes=1048576,
        temp_bytes=1048576,
        temp_root="/tmp/lane",
        exit_state="passed",
    )
    non_benchmark_receipt = harness.DonorErScaleSpikeReceipt(
        schema_version="donor_er_scale_spike.v1",
        rows_sha256="d" * 64,
        observations=(non_benchmark_observation,),
    )
    with pytest.raises(ValidationError, match="passed benchmark receipt"):
        harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, benchmark=non_benchmark_receipt))


def test_architecture_receipt_resource_and_cleanup_evidence_are_required_not_defaulting_healthy() -> None:
    harness = _load_harness()
    for missing in ("resource_locality", "cleanup_evidence"):
        kwargs = _go_receipt_kwargs(harness)
        kwargs.pop(missing)
        with pytest.raises(ValidationError, match="Field required"):
            harness.DonorErArchitectureReceipt(**kwargs)
    for missing in ("execution_locality", "peak_rss_bytes", "memory_budget_bytes"):
        resource_kwargs = _resource_locality_kwargs()
        resource_kwargs.pop(missing)
        with pytest.raises(ValidationError, match="Field required"):
            harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness, resource_locality=resource_kwargs))


def test_architecture_receipt_cleanup_evidence_is_paths_and_absence_only() -> None:
    harness = _load_harness()
    cleanup_fields = harness.CleanupEvidence.model_fields
    # Cleanup evidence carries only string paths, absence booleans, and counts.
    assert set(cleanup_fields) == {
        "data_root_path",
        "data_root_created",
        "data_root_removed",
        "temp_root_path",
        "temp_root_created",
        "temp_root_removed",
        "credential_root_path",
        "credential_root_absent",
        "credential_paths",
        "credential_files_present",
        "lane_pid_count",
        "lane_proxy_count",
    }

    for secret in (
        "PGPASSWORD=super-secret-token",
        "postgresql://user:pass@localhost/db",
        "line1\nSECRET_FILE_CONTENTS",
    ):
        kwargs = _go_receipt_kwargs(harness)
        kwargs["cleanup_evidence"] = {**_cleanup_kwargs(), "credential_paths": [secret]}
        with pytest.raises(ValidationError) as error_info:
            harness.DonorErArchitectureReceipt(**kwargs)
        # The scrub owner reports the field location but never the secret-bearing value.
        scrubbed = harness._scrubbed_validation_message(error_info.value)
        assert secret not in scrubbed
        assert "credential_paths" in scrubbed


def test_validate_receipt_no_longer_returns_deferred_stage_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    receipt = harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness))
    receipt_path = tmp_path / "receipt.md"
    receipt_path.write_text(_receipt_markdown(receipt.model_dump_json()), encoding="utf-8")

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path)]) == 0
    captured = capsys.readouterr()
    assert "deferred" not in captured.err.lower()
    assert "b2_disposition=GO" in captured.out
    assert "terminal_disposition=ADOPT_BOUNDED_SINGLE_NODE" in captured.out


def test_validate_receipt_emit_json_writes_single_validated_object(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    receipt = harness.DonorErArchitectureReceipt(**_no_go_receipt_kwargs(harness, "UNCLASSIFIED"))
    receipt_path = tmp_path / "receipt.md"
    receipt_path.write_text(_receipt_markdown(receipt.model_dump_json()), encoding="utf-8")

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path), "--emit-validated-json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    stdout = captured.out.strip()
    # Exactly one JSON value on stdout, no summaries or narrative.
    assert stdout.startswith("{") and stdout.endswith("}")
    assert "validate-receipt" not in stdout
    payload = json.loads(stdout)
    assert payload["b2_disposition"] == "NO_GO"
    assert payload["b2_blocker_class"] == "UNCLASSIFIED"
    assert payload["terminal_disposition"] == "MEASUREMENT_NOT_READY"


@pytest.mark.parametrize(
    "missing_version_paths",
    [
        (("schema_version",),),
        (("benchmark", "schema_version"),),
        (("schema_version",), ("benchmark", "schema_version")),
    ],
    ids=["architecture", "nested_benchmark", "both"],
)
def test_validate_receipt_requires_explicit_schema_versions_before_json_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_version_paths: tuple[tuple[str, ...], ...],
) -> None:
    harness = _load_harness()
    payload = _receipt_payload(harness, _go_receipt_kwargs(harness))
    for missing_version_path in missing_version_paths:
        target: dict[str, Any] = payload
        for key in missing_version_path[:-1]:
            target = target[key]
        del target[missing_version_path[-1]]
    receipt_path = _write_markdown(tmp_path / "missing_schema_version.md", _receipt_markdown(json.dumps(payload)))

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt-path",
                str(receipt_path),
                "--emit-validated-json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "schema_version" in captured.err


def _write_markdown(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_validate_receipt_rejects_malformed_fences(tmp_path: Path) -> None:
    harness = _load_harness()
    valid_json = harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness)).model_dump_json()

    no_fence = _write_markdown(tmp_path / "no_fence.md", f"# Receipt\n\nProse only: {valid_json}\n")
    wrong_language = _write_markdown(tmp_path / "wrong_lang.md", _receipt_markdown(valid_json, language="json"))
    narrative_outside_fence = _write_markdown(
        tmp_path / "narrative_outside_fence.md",
        _receipt_markdown_with_narrative(valid_json),
    )
    multiple = _write_markdown(
        tmp_path / "multi.md",
        _receipt_markdown(valid_json) + _receipt_markdown(valid_json),
    )
    malformed = _write_markdown(tmp_path / "malformed.md", _receipt_markdown('{"b2_disposition": '))

    for path in (no_fence, wrong_language, multiple, malformed):
        assert harness.main(["validate-receipt", "--receipt-path", str(path)]) == 1

    # Narrative around a single fence is the published report shape and is
    # accepted; only the fenced object is parsed. Covered in depth by
    # test_single_fenced_receipt_json_trusts_one_fence_inside_narrative.
    assert harness.main(["validate-receipt", "--receipt-path", str(narrative_outside_fence)]) == 0


def test_validate_receipt_rejects_longer_fence_info_string(tmp_path: Path) -> None:
    harness = _load_harness()
    valid_json = harness.DonorErArchitectureReceipt(**_go_receipt_kwargs(harness)).model_dump_json()
    receipt_path = _write_markdown(
        tmp_path / "longer_info_string.md",
        _receipt_markdown(valid_json, language="donor_er_scale_spike_receipt_extra"),
    )

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path)]) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"terminal_disposition": "ADOPT_MYSTERY"},
        {"b2_disposition": "MAYBE"},
        {"b2_blocker_class": "SOMETHING_ELSE"},
        {"benchmark": None},
        {"resource_locality": None},
    ],
    ids=["unknown_terminal", "unknown_disposition", "unknown_blocker", "missing_observations", "missing_resource"],
)
def test_validate_receipt_rejects_invalid_receipt_content(tmp_path: Path, mutation: dict[str, object]) -> None:
    harness = _load_harness()
    payload = _receipt_payload(harness, _go_receipt_kwargs(harness))
    payload.update(mutation)
    if mutation.get("resource_locality") is None:
        del payload["resource_locality"]
    receipt_path = _write_markdown(tmp_path / "bad.md", _receipt_markdown(json.dumps(payload)))

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path)]) == 1


def test_validate_receipt_scrubs_credential_looking_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    secret = "PGPASSWORD=super-secret-token-1234"
    payload = _receipt_payload(harness, _go_receipt_kwargs(harness))
    payload["cleanup_evidence"]["credential_paths"] = [secret]
    receipt_path = _write_markdown(tmp_path / "leaky.md", _receipt_markdown(json.dumps(payload)))

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path)]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "super-secret-token-1234" not in captured.err
    # The field location is still reported so the failure is diagnosable.
    assert "credential_paths" in captured.err


def test_validate_receipt_scrubs_secret_bearing_field_locations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    secret_key = "PGPASSWORD=super-secret-token-4242"
    payload = _receipt_payload(harness, _go_receipt_kwargs(harness))
    payload[secret_key] = "extra receipt-controlled key"
    receipt_path = _write_markdown(tmp_path / "leaky_location.md", _receipt_markdown(json.dumps(payload)))

    assert harness.main(["validate-receipt", "--receipt-path", str(receipt_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret_key not in captured.err
    assert "super-secret-token-4242" not in captured.err
    assert "<redacted>" in captured.err


@pytest.mark.parametrize(
    "secret",
    [
        "PGPASSWORD=super-secret-token-5678",
        "AWS_ACCESS_KEY_ID=AKIATESTVALUE",
    ],
    ids=["pgpassword", "aws_access_key_id"],
)
def test_validate_receipt_rejects_secret_bearing_rerun_command_before_json_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    secret: str,
) -> None:
    harness = _load_harness()
    payload = _receipt_payload(harness, _no_go_receipt_kwargs(harness))
    payload["blocker_evidence"]["rerun_command"] = f"{secret} uv run donor-er-benchmark"
    receipt_path = _write_markdown(tmp_path / "leaky_rerun.md", _receipt_markdown(json.dumps(payload)))

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt-path",
                str(receipt_path),
                "--emit-validated-json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert secret.split("=", 1)[1] not in captured.err


def test_validate_receipt_preserves_non_secret_multiline_source_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    payload = _receipt_payload(harness, _no_go_receipt_kwargs(harness))
    payload["b2_source"]["verbatim_verdict"] = "B2: NO-GO\ncapacity evidence remains unresolved"
    payload["blocker_evidence"]["source_evidence"] = "capacity probe exceeded memory\nrerun stayed local"
    receipt_path = _write_markdown(tmp_path / "multiline.md", _receipt_markdown(json.dumps(payload)))

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt-path",
                str(receipt_path),
                "--emit-validated-json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    validated_payload = json.loads(captured.out)
    assert validated_payload["b2_source"]["verbatim_verdict"] == payload["b2_source"]["verbatim_verdict"]
    assert validated_payload["blocker_evidence"]["source_evidence"] == payload["blocker_evidence"]["source_evidence"]

    payload["blocker_evidence"]["source_evidence"] = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    leaky_receipt_path = _write_markdown(tmp_path / "leaky_multiline.md", _receipt_markdown(json.dumps(payload)))
    assert harness.main(["validate-receipt", "--receipt-path", str(leaky_receipt_path)]) == 1


def test_validate_receipt_rejects_newline_delimited_secret_assignment_before_json_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    secret = "PGPASSWORD=super-secret-token-9012"
    payload = _receipt_payload(harness, _no_go_receipt_kwargs(harness))
    payload["blocker_evidence"]["source_evidence"] = f"first line\n{secret}"
    receipt_path = _write_markdown(tmp_path / "leaky_multiline_assignment.md", _receipt_markdown(json.dumps(payload)))

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt-path",
                str(receipt_path),
                "--emit-validated-json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert secret.split("=", 1)[1] not in captured.err


def test_architecture_receipt_allows_equality_prose_but_rejects_shell_assignments() -> None:
    harness = _load_harness()
    for detail in ("COUNT = 1", "STATE = NC"):
        receipt = harness.DonorErArchitectureReceipt(
            **_no_go_receipt_kwargs(
                harness,
                blocker_evidence={
                    **_no_go_receipt_kwargs(harness)["blocker_evidence"],
                    "detail": detail,
                },
            )
        )
        assert receipt.blocker_evidence.detail == detail

    payload = _no_go_receipt_kwargs(harness)
    payload["blocker_evidence"] = {
        **payload["blocker_evidence"],
        "rerun_command": "PGPASSWORD=secret uv run donor-er-benchmark",
    }
    with pytest.raises(ValidationError, match="environment assignments"):
        harness.DonorErArchitectureReceipt(**payload)


def test_known_answer_signature_bytes_and_row_hashes_distinguish_blank_employer() -> None:
    harness = _load_harness()
    blank_employer_row = {
        "NAME": "Doe, Jane Q",
        "EMPLOYER": " ",
        "OCCUPATION": " Engineer ",
        "CITY": " raleigh ",
        "STATE": "North Carolina",
        "ZIP_CODE": "27601-1234",
    }
    present_employer_row = {
        **blank_employer_row,
        "EMPLOYER": " Acme Corp ",
    }

    blank_bytes = harness.diagnostic_signature_bytes(blank_employer_row)
    present_bytes = harness.diagnostic_signature_bytes(present_employer_row)

    assert blank_bytes == b'["JANE Q DOE",null,"Engineer","RALEIGH","NC","27601"]'
    assert present_bytes == b'["JANE Q DOE","Acme Corp","Engineer","RALEIGH","NC","27601"]'
    assert harness.normalized_benchmark_row_id(blank_employer_row) == hashlib.sha256(blank_bytes).hexdigest()
    assert harness.normalized_benchmark_row_id(present_employer_row) == hashlib.sha256(present_bytes).hexdigest()
    assert (
        harness.normalized_benchmark_rows_sha256([present_employer_row, blank_employer_row])
        == hashlib.sha256(b"".join(sorted([present_bytes, blank_bytes]))).hexdigest()
    )


def test_signature_helper_calls_canonical_owner_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _load_harness()
    calls: list[tuple[str, Any]] = []

    class Parsed:
        canonical = "PATCHED CANONICAL"

    class Address:
        city = "PATCHED CITY"
        state = "PC"
        zip5 = "12345"

    def parse_name(value: str | None) -> Parsed:
        calls.append(("parse_name", value))
        return Parsed()

    def normalize_address(*, city: str | None = None, state: str | None = None, zip: str | None = None) -> Address:
        calls.append(("normalize_address", (city, state, zip)))
        return Address()

    def map_contribution_fields(row: dict[str, str | None]) -> dict[str, object]:
        calls.append(("map_contribution_fields", row))
        return {
            "contributor_name": "Raw Person",
            "contributor_employer": "Mapped Employer",
            "contributor_occupation": "Mapped Occupation",
            "contributor_city": "Raw City",
            "contributor_state": "Raw State",
            "contributor_zip": "12345-6789",
        }

    monkeypatch.setattr(harness, "parse_name", parse_name)
    monkeypatch.setattr(harness, "normalize_address", normalize_address)
    monkeypatch.setattr(harness, "map_contribution_fields", map_contribution_fields)

    assert harness.diagnostic_signature_bytes({"NAME": "ignored"}) == (
        b'["PATCHED CANONICAL","Mapped Employer","Mapped Occupation","PATCHED CITY","PC","12345"]'
    )
    assert calls == [
        ("map_contribution_fields", {"NAME": "ignored"}),
        ("parse_name", "Raw Person"),
        ("normalize_address", ("Raw City", "Raw State", "12345-6789")),
    ]


def test_harness_exports_canonical_er_owner_import_references(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _load_harness()
    names = importlib.import_module("domains.campaign_finance.normalize.names")
    addresses = importlib.import_module("domains.campaign_finance.normalize.addresses")
    field_mapper = importlib.import_module("domains.campaign_finance.ingest.field_mapper")
    blocking = importlib.import_module("core.entity_resolution.blocking")
    splink_config = importlib.import_module("core.entity_resolution.splink_config")
    scoring = importlib.import_module("core.entity_resolution.scoring")

    assert harness.parse_name is names.parse_name
    assert harness.normalize_address is addresses.normalize_address
    assert harness.map_contribution_fields is field_mapper.map_contribution_fields
    assert harness.describe_blocking_rules is blocking.describe_blocking_rules
    assert harness.get_blocking_rule_sqls is splink_config.get_blocking_rule_sqls
    assert harness.score_rows is scoring.score_rows

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        harness, "describe_blocking_rules", lambda entity_type: calls.append(("describe", entity_type)) or []
    )
    monkeypatch.setattr(
        harness, "get_blocking_rule_sqls", lambda entity_type: calls.append(("rules", entity_type)) or []
    )
    monkeypatch.setattr(
        harness,
        "score_rows",
        lambda rows, entity_type, **kwargs: calls.append(("score", entity_type, kwargs)) or [],
    )

    assert harness.blocking_rule_metadata("person") == {"descriptions": [], "sqls": []}
    assert harness.score_diagnostic_rows([], "person") == []
    assert calls == [("describe", "person"), ("rules", "person"), ("score", "person", {"include_diagnostics": True})]


def _valid_pair_attribution_artifact_kwargs() -> dict[str, object]:
    return {
        "schema_version": "donor_er_pair_attribution.v1",
        "pairs": [
            {
                "entity_id_a": "donor-001",
                "entity_id_b": "donor-002",
                "match_key": "0",
                "blocking_rule_sql": "l.last_name = r.last_name",
                "match_weight": 8.5,
                "match_probability": 0.93,
                "comparison_fields": [
                    {"field_name": "gamma_name", "value": 2},
                    {"field_name": "bf_name", "value": 64.0},
                ],
            }
        ],
    }


def test_donor_pair_attribution_artifact_schema_is_closed_known_answer() -> None:
    harness = _load_harness()

    artifact = harness.DonorPairAttributionArtifact(**_valid_pair_attribution_artifact_kwargs())

    assert artifact.model_dump(mode="python") == _valid_pair_attribution_artifact_kwargs()
    assert harness.DonorPairAttributionArtifact.model_config["extra"] == "forbid"
    assert harness.DonorPairAttributionPair.model_config["extra"] == "forbid"
    assert harness.DonorPairComparisonField.model_config["extra"] == "forbid"
    assert set(harness.DonorPairAttributionArtifact.model_fields) == {"schema_version", "pairs"}
    assert set(harness.DonorPairAttributionPair.model_fields) == {
        "entity_id_a",
        "entity_id_b",
        "match_key",
        "blocking_rule_sql",
        "match_weight",
        "match_probability",
        "comparison_fields",
    }
    assert set(harness.DonorPairComparisonField.model_fields) == {"field_name", "value"}


@pytest.mark.parametrize(
    ("case_name", "mutator", "match"),
    [
        (
            "missing_pair_field",
            lambda payload: payload["pairs"][0].pop("match_weight"),
            "match_weight",
        ),
        (
            "unknown_artifact_field",
            lambda payload: payload.update({"extra_artifact": "forbidden"}),
            "extra",
        ),
        (
            "unknown_pair_field",
            lambda payload: payload["pairs"][0].update({"extra_pair": "forbidden"}),
            "extra",
        ),
        (
            "unknown_comparison_field",
            lambda payload: payload["pairs"][0]["comparison_fields"][0].update({"extra_comparison": "forbidden"}),
            "extra",
        ),
        (
            "empty_comparison_evidence",
            lambda payload: payload["pairs"][0].update({"comparison_fields": []}),
            "comparison",
        ),
        (
            "invalid_comparison_prefix",
            lambda payload: payload["pairs"][0]["comparison_fields"][0].update({"field_name": "name"}),
            "gamma_",
        ),
        (
            "missing_bf_prefix",
            lambda payload: payload["pairs"][0].update(
                {"comparison_fields": [{"field_name": "gamma_name", "value": 2}]}
            ),
            "bf_",
        ),
        (
            "missing_gamma_prefix",
            lambda payload: payload["pairs"][0].update(
                {"comparison_fields": [{"field_name": "bf_name", "value": 64.0}]}
            ),
            "gamma_",
        ),
        (
            "unpaired_comparison_evidence",
            lambda payload: payload["pairs"][0].update(
                {
                    "comparison_fields": [
                        {"field_name": "gamma_name", "value": 2},
                        {"field_name": "bf_zip5", "value": 16.0},
                    ]
                }
            ),
            "paired",
        ),
        (
            "non_finite_match_weight",
            lambda payload: payload["pairs"][0].update({"match_weight": float("nan")}),
            "finite",
        ),
        (
            "worktree_absolute_path",
            lambda payload: payload["pairs"][0].update({"blocking_rule_sql": str(REPO_ROOT / "secret.sql")}),
            "repository",
        ),
        (
            "environment_assignment",
            lambda payload: payload["pairs"][0]["comparison_fields"][1].update({"value": "DATABASE_URL=postgres://x"}),
            "environment",
        ),
        (
            "secret_bearing_string",
            lambda payload: payload["pairs"][0]["comparison_fields"][1].update(
                {"value": "-----BEGIN PRIVATE KEY-----"}
            ),
            "file contents",
        ),
    ],
)
def test_donor_pair_attribution_artifact_rejects_invalid_inputs(
    case_name: str,
    mutator: object,
    match: str,
) -> None:
    harness = _load_harness()
    payload = _valid_pair_attribution_artifact_kwargs()
    mutator(payload)

    with pytest.raises(ValidationError) as error_info:
        harness.DonorPairAttributionArtifact(**payload)

    scrubbed = harness._scrubbed_validation_message(error_info.value)
    assert match in scrubbed, case_name
    assert "DATABASE_URL=postgres://x" not in scrubbed
    assert "PRIVATE KEY" not in scrubbed


def test_build_donor_pair_attribution_artifact_filters_sample_and_resolves_blocking_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    clusters = [
        {"cluster_id": "cluster-a", "member_ids": ["donor-001", "donor-002"]},
        {"cluster_id": "cluster-b", "member_ids": ["donor-003", "donor-004"]},
    ]
    sampled_member_ids = {
        member_id
        for cluster in harness.select_deterministic_cluster_sample(clusters, seed="artifact-seed", size=1)
        for member_id in cluster["member_ids"]
    }
    scored_pairs = [
        {
            "entity_id_a": "donor-001",
            "entity_id_b": "donor-002",
            "confidence": 0.93,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "match_key": 0,
            "match_weight": 8.5,
            "match_probability": 0.93,
            "gamma_name": 2,
            "bf_name": 64.0,
        },
        {
            "entity_id_a": "donor-003",
            "entity_id_b": "donor-004",
            "confidence": 0.91,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
            "match_key": 1,
            "match_weight": 7.25,
            "match_probability": 0.91,
            "gamma_name": 1,
            "bf_name": 16.0,
        },
    ]
    monkeypatch.setattr(
        harness,
        "describe_blocking_rules",
        lambda entity_type: [
            {"rule_index": 0, "blocking_rule": "readable rule zero"},
            {"rule_index": 1, "blocking_rule": "readable rule one"},
        ],
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object(), object()])

    artifact = harness.build_donor_pair_attribution_artifact(
        scored_pairs=scored_pairs,
        sampled_member_ids=sampled_member_ids,
        entity_type="person",
    )

    assert artifact.model_dump(mode="python") == {
        "schema_version": "donor_er_pair_attribution.v1",
        "pairs": [
            {
                "entity_id_a": "donor-001",
                "entity_id_b": "donor-002",
                "match_key": 0,
                "blocking_rule_sql": "readable rule zero",
                "match_weight": 8.5,
                "match_probability": 0.93,
                "comparison_fields": [
                    {"field_name": "gamma_name", "value": 2},
                    {"field_name": "bf_name", "value": 64.0},
                ],
            }
        ],
    }
    assert all(
        pair_id in sampled_member_ids
        for pair in artifact.model_dump(mode="python")["pairs"]
        for pair_id in (pair["entity_id_a"], pair["entity_id_b"])
    )

    string_key_artifact = harness.build_donor_pair_attribution_artifact(
        scored_pairs=[scored_pairs[0] | {"match_key": "0"}],
        sampled_member_ids=sampled_member_ids,
        entity_type="person",
    )
    assert string_key_artifact.pairs[0].blocking_rule_sql == "readable rule zero"


@pytest.mark.parametrize("bad_match_key", ["x", "-1", "2"])
def test_build_donor_pair_attribution_artifact_rejects_invalid_blocking_match_key(
    monkeypatch: pytest.MonkeyPatch,
    bad_match_key: str,
) -> None:
    harness = _load_harness()
    payload = _valid_pair_attribution_artifact_kwargs()["pairs"][0]
    payload["match_key"] = bad_match_key
    monkeypatch.setattr(
        harness, "describe_blocking_rules", lambda entity_type: [{"rule_index": 0, "blocking_rule": "r0"}]
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object()])

    with pytest.raises(ValueError, match="match_key"):
        harness.build_donor_pair_attribution_artifact(
            scored_pairs=[payload],
            sampled_member_ids={"donor-001", "donor-002"},
            entity_type="person",
        )


def test_build_donor_pair_attribution_artifact_rejects_mismatched_blocking_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    payload = _valid_pair_attribution_artifact_kwargs()["pairs"][0]
    monkeypatch.setattr(
        harness, "describe_blocking_rules", lambda entity_type: [{"rule_index": 0, "blocking_rule": "r0"}]
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object(), object()])

    with pytest.raises(ValueError, match="blocking"):
        harness.build_donor_pair_attribution_artifact(
            scored_pairs=[payload],
            sampled_member_ids={"donor-001", "donor-002"},
            entity_type="person",
        )


def test_build_donor_pair_attribution_artifact_rejects_misaligned_blocking_rule_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    payload = _valid_pair_attribution_artifact_kwargs()["pairs"][0]
    monkeypatch.setattr(
        harness,
        "describe_blocking_rules",
        lambda entity_type: [
            {"rule_index": 1, "blocking_rule": "misindexed r0"},
            {"rule_index": 0, "blocking_rule": "misindexed r1"},
        ],
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object(), object()])

    with pytest.raises(ValueError, match="blocking"):
        harness.build_donor_pair_attribution_artifact(
            scored_pairs=[payload],
            sampled_member_ids={"donor-001", "donor-002"},
            entity_type="person",
        )


def test_harness_does_not_define_parallel_normalization_mapping_blocking_or_scoring_logic() -> None:
    source = (REPO_ROOT / "scripts" / "donor_er_scale_spike.py").read_text(encoding="utf-8")

    forbidden_snippets = (
        "KNOWN_SUFFIXES",
        "STATE_ABBREVIATIONS",
        "blocking_rules_to_generate_predictions",
        "match_probability",
        "def parse_name",
        "def normalize_address",
        "def map_contribution_fields",
        "def score_rows",
    )
    for snippet in forbidden_snippets:
        assert snippet not in source
    assert "donor_key" not in source
    assert "person_id" not in source


def _mapped_schedule_a_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sub_id": "survivor",
        "contribution_receipt_date": "2024-01-15",
        "transaction_type": "15",
        "entity_type": "IND",
        "memo_code": None,
        "amendment_indicator": "N",
    }
    row.update(overrides)
    return row


def test_mapped_schedule_a_eligibility_survivor_ids_cover_sql_equivalent_filters() -> None:
    contract = importlib.import_module("api.contribution_insights_contract")
    rows = [
        _mapped_schedule_a_row(sub_id="kept_none_memo"),
        _mapped_schedule_a_row(sub_id="kept_blank_memo", memo_code=""),
        _mapped_schedule_a_row(sub_id="drop_memo_x", memo_code="X"),
        _mapped_schedule_a_row(sub_id="drop_memo_lower_x", memo_code="x"),
        _mapped_schedule_a_row(sub_id="drop_terminated", amendment_indicator="T"),
        _mapped_schedule_a_row(sub_id="drop_non_receipt", transaction_type="22Y"),
        _mapped_schedule_a_row(sub_id="drop_invalid_date", contribution_receipt_date="20240231"),
        _mapped_schedule_a_row(sub_id="drop_missing_date", contribution_receipt_date=None),
        _mapped_schedule_a_row(sub_id="drop_before_min_date", contribution_receipt_date="2021-12-31"),
        _mapped_schedule_a_row(sub_id="drop_missing_transaction_type", transaction_type=None),
        _mapped_schedule_a_row(sub_id="drop_blank_transaction_type", transaction_type=" "),
        _mapped_schedule_a_row(sub_id="drop_missing_entity_type", entity_type=None),
        _mapped_schedule_a_row(sub_id="drop_missing_amendment", amendment_indicator=None),
        _mapped_schedule_a_row(sub_id="drop_blank_amendment", amendment_indicator=" "),
        _mapped_schedule_a_row(sub_id="drop_non_ind", entity_type="ORG"),
    ]

    survivor_ids = [row["sub_id"] for row in rows if contract.is_contribution_insights_mapped_row(row)]

    assert survivor_ids == ["kept_none_memo", "kept_blank_memo"]


def test_harness_imports_canonical_fec_bulk_root_helper_and_rejects_repo_cache_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    fec_bulk_files = importlib.import_module("domains.campaign_finance.ingest.fec_bulk_files")
    repo_cache_root = fec_bulk_files.fec_bulk_data_root(REPO_ROOT / "data").resolve()
    calls: list[str] = []
    monkeypatch.setattr(harness, "read_bulk_file", lambda *args, **kwargs: calls.append("read") or iter(()))

    assert harness.fec_bulk_data_root is fec_bulk_files.fec_bulk_data_root
    for path in [repo_cache_root, repo_cache_root / "2026"]:
        with pytest.raises(ValueError, match="repository FEC bulk cache"):
            harness._materialize(_materialize_args(tmp_path, data_root=str(path)))

    assert calls == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("data_root", "postgresql://user:pass@localhost/db", "database"),
        ("committee_id_file", "host=localhost dbname=civibus", "database"),
        ("archive_url", "https://example.invalid/indiv26.zip", "network"),
        ("output_path", "fly://app/tmp/normalized_rows.jsonl", "Fly"),
        ("output_path", "outside", "output-path"),
        ("cohort_size", 101, "cohort-size"),
    ],
)
def test_materialize_rejects_unsafe_arguments_before_archive_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    harness = _load_harness()
    if value == "outside":
        value = str(tmp_path / "outside.jsonl")
    monkeypatch.setattr(
        harness,
        "read_bulk_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive rows must not be read")),
    )

    with pytest.raises(ValueError, match=message):
        harness._materialize(_materialize_args(tmp_path, **{field: value}))


@pytest.mark.parametrize(
    ("committee_ids", "expected_count", "sha_override", "message"),
    [
        (["C00100002", "C00100001"], 2, None, "sorted"),
        (["C00100001", "C00100001"], 2, None, "duplicate"),
        (["C00100001", "C00100002"], 3, None, "count"),
        (["C00100001", "C00100002"], 2, "0" * 64, "SHA-256"),
    ],
)
def test_committee_evidence_is_validated_before_archive_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    committee_ids: list[str],
    expected_count: int,
    sha_override: str | None,
    message: str,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    committee_file = temp_root / "committee_ids.txt"
    _write_committee_file(committee_file, committee_ids)
    monkeypatch.setattr(
        harness,
        "read_bulk_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive rows must not be read")),
    )

    with pytest.raises(ValueError, match=message):
        harness._materialize(
            _materialize_args(
                tmp_path,
                committee_id_file=str(committee_file),
                expected_committee_count=expected_count,
                committee_id_file_sha256=sha_override or _sha256_file(committee_file),
            )
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"archive_url": "https://example.invalid/indiv26.zip"}, "network"),
        ({"archive_url": None}, "data-root"),
        ({"archive_size_bytes": 1}, "size"),
        ({"archive_sha256": "1" * 64}, "SHA-256"),
        ({"archive_member_name": "wrong.txt"}, "member"),
    ],
)
def test_archive_evidence_is_validated_before_row_processing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    harness = _load_harness()
    if overrides.get("archive_url") is None and "archive_url" in overrides:
        outside_archive = tmp_path / "outside.zip"
        _write_itcont_zip(outside_archive)
        overrides = {
            **overrides,
            "archive_url": str(outside_archive),
            "archive_sha256": _sha256_file(outside_archive),
            "archive_size_bytes": outside_archive.stat().st_size,
        }
    if overrides.get("archive_member_name") == "wrong.txt":
        monkeypatch.setattr(
            harness,
            "map_contribution_fields",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive rows must not be mapped")),
        )
    else:
        monkeypatch.setattr(
            harness,
            "read_bulk_file",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive rows must not be read")),
        )

    with pytest.raises(ValueError, match=message):
        harness._materialize(_materialize_args(tmp_path, **overrides))


def test_materialize_uses_bounded_duckdb_config_before_archive_iteration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    events: list[str] = []

    def open_connection(config: Any) -> Any:
        events.append(f"open:{config.database_path.name}:{config.temp_root.name}")
        raise RuntimeError("DuckDB memory_limit is looser than the requested byte budget")

    monkeypatch.setattr(harness, "open_bounded_duckdb_connection", open_connection)
    monkeypatch.setattr(
        harness,
        "read_bulk_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive rows must not be read")),
    )

    with pytest.raises(RuntimeError, match="memory_limit"):
        harness._materialize(_materialize_args(tmp_path))

    with pytest.raises(ValueError, match=r"default \.tmp"):
        dot_tmp = tmp_path / "lane" / ".tmp"
        dot_tmp.mkdir()
        harness._materialize(
            _materialize_args(
                tmp_path,
                temp_root=str(dot_tmp),
                output_path=str(dot_tmp / "normalized_rows.jsonl"),
            )
        )

    with pytest.raises(ValueError, match="temp-root"):
        outside_temp = tmp_path / "outside"
        outside_temp.mkdir()
        harness._materialize(_materialize_args(tmp_path, temp_root=str(outside_temp)))

    assert events == ["open:donor_er_scale_spike.duckdb:lane"]


def test_materialize_reads_itcont_zip_through_canonical_parser_with_expected_member(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    calls: list[tuple[Path, str, str | None]] = []

    class FakeConnection:
        def close(self) -> None:
            calls.append((Path("closed"), "close", None))

    def fake_read_bulk_file(path: Path, file_type: str, **kwargs: object) -> list[dict[str, str | None]]:
        calls.append((path, file_type, kwargs.get("expected_member_name")))
        return []

    monkeypatch.setattr(harness, "open_bounded_duckdb_connection", lambda _config: FakeConnection())
    monkeypatch.setattr(harness, "read_bulk_file", fake_read_bulk_file)
    monkeypatch.setattr(
        harness,
        "_materialized_rows",
        lambda *args, **kwargs: list(
            fake_read_bulk_file(kwargs["archive_path"], "itcont", expected_member_name=kwargs["archive_member_name"])
        ),
    )

    assert harness._materialize(_materialize_args(tmp_path, archive_member_name="itcont.txt")) == 0

    assert calls == [
        (tmp_path / "data" / "indiv26.zip", "itcont", "itcont.txt"),
        (Path("closed"), "close", None),
    ]


def test_materialize_applies_diagnostic_committee_and_name_filters_and_writes_models(tmp_path: Path) -> None:
    harness = _load_harness()
    archive_path = tmp_path / "data" / "indiv26.zip"
    rows = [
        _itcont_row(name="DOE, JANE", sub_id="1"),
        _itcont_row(name=" ", sub_id="2"),
        _itcont_row(committee_id="C00999999", name="SMITH, JOHN", sub_id="3"),
        _itcont_row(name="MEMO, MAX", memo_code="X", sub_id="4"),
        _itcont_row(name="ORG, ACME", entity_type="ORG", sub_id="5"),
    ]
    _write_itcont_zip(archive_path, rows=rows)

    args = _materialize_args(
        tmp_path,
        archive_sha256=_sha256_file(archive_path),
        archive_size_bytes=archive_path.stat().st_size,
    )

    assert harness._materialize(args) == 0
    output_rows = _materialized_json_rows(Path(args.output_path), harness)

    assert len(output_rows) == 1
    assert output_rows[0].canonical_name == "JANE DOE"
    assert output_rows[0].employer == "ACME"


def test_materialize_collapses_exact_signatures_and_distinguishes_null_employer(tmp_path: Path) -> None:
    harness = _load_harness()
    archive_path = tmp_path / "data" / "indiv26.zip"
    fec_name = harness.parse_name("DOE, DR JANE QUINN JR")
    natural_name = harness.parse_name("Dr Jane Quinn Doe Jr")
    rows = [
        _itcont_row(name="DOE, DR JANE QUINN JR", employer="", sub_id="1"),
        _itcont_row(name="Dr Jane Quinn Doe Jr", employer=" ", city="raleigh", state="North Carolina", sub_id="2"),
        _itcont_row(name="DOE, DR JANE QUINN JR", employer="ACME", sub_id="3"),
    ]
    _write_itcont_zip(archive_path, rows=rows)
    args = _materialize_args(
        tmp_path,
        archive_sha256=_sha256_file(archive_path),
        archive_size_bytes=archive_path.stat().st_size,
    )

    expected_name = ("DR", "JANE", "DOE", "JANE Q DOE JR")
    assert (fec_name.prefix, fec_name.first, fec_name.last, fec_name.canonical) == expected_name
    assert (natural_name.prefix, natural_name.first, natural_name.last, natural_name.canonical) == expected_name
    assert harness._materialize(args) == 0
    output_rows = _materialized_json_rows(Path(args.output_path), harness)

    assert len(output_rows) == 2
    assert {row.employer for row in output_rows} == {None, "ACME"}
    assert {row.canonical_name for row in output_rows} == {"JANE Q DOE JR"}


def test_materialize_sha_ordered_cohorts_are_reorder_stable_and_strictly_nested(tmp_path: Path) -> None:
    harness = _load_harness()
    source_rows = [
        _itcont_row(name="ALPHA, ANN", sub_id="1"),
        _itcont_row(name="BRAVO, BEN", city="DURHAM", zip_code="27701", sub_id="2"),
        _itcont_row(name="CHARLIE, CAM", city="CARY", zip_code="27511", sub_id="3"),
    ]

    def run_case(case_dir: Path, rows: list[str], cohort_size: int) -> list[str]:
        archive_path = case_dir / "data" / "indiv26.zip"
        _write_itcont_zip(archive_path, rows=rows)
        args = _materialize_args(
            case_dir,
            cohort_size=cohort_size,
            archive_sha256=_sha256_file(archive_path),
            archive_size_bytes=archive_path.stat().st_size,
        )
        assert harness._materialize(args) == 0
        return [row.row_id for row in _materialized_json_rows(Path(args.output_path), harness)]

    first_two = run_case(tmp_path / "case_a", source_rows, 2)
    all_three = run_case(tmp_path / "case_b", source_rows, 3)
    reordered_first_two = run_case(tmp_path / "case_c", list(reversed(source_rows)), 2)

    assert first_two == reordered_first_two
    assert all_three[:2] == first_two
    assert len(all_three) == 3
    assert all_three == sorted(all_three)


def _known_answer_benchmark_rows(harness: Any) -> list[Any]:
    return [
        harness.NormalizedBenchmarkRow(
            row_id="b",
            canonical_name="DOE, JANE",
            employer="ACME",
            occupation="ENGINEER",
            city="RALEIGH",
            state="NC",
            zip5="27601",
        ),
        harness.NormalizedBenchmarkRow(
            row_id="a",
            canonical_name="SMITH, JOHN",
            employer=None,
            occupation="LAWYER",
            city="RALEIGH",
            state="NC",
            zip5="27601",
        ),
        harness.NormalizedBenchmarkRow(
            row_id="c",
            canonical_name="DOE, JANE",
            employer="ACME",
            occupation=None,
            city=None,
            state="NC",
            zip5="27601",
        ),
        harness.NormalizedBenchmarkRow(
            row_id="c",
            canonical_name="DOE, JANE",
            employer="ACME",
            occupation=None,
            city=None,
            state="NC",
            zip5="27601",
        ),
    ]


def _patch_known_answer_blocking(
    monkeypatch: pytest.MonkeyPatch,
    harness: Any,
    calls: dict[str, object],
) -> None:
    class FakeConnection:
        def close(self) -> None:
            calls["closed"] = True

    def fake_open_connection(config: object) -> FakeConnection:
        calls["config"] = config
        return FakeConnection()

    def fake_count_blocked_pairs(
        er_rows: list[dict[str, object]], entity_type: str, **kwargs: object
    ) -> list[dict[str, object]]:
        calls["er_rows"] = er_rows
        calls["entity_type"] = entity_type
        bounded_connection = kwargs["bounded_connection_factory"]()
        calls["bounded_connection"] = bounded_connection
        bounded_connection.close()
        return [
            {
                "rule_index": 0,
                "blocking_rule": "l.last_name = r.last_name AND l.state = r.state",
                "exclusive_pair_count": 3,
                "cumulative_pair_count": 3,
                "max_block_size": 3,
            },
            {
                "rule_index": 1,
                "blocking_rule": "l.zip5 = r.zip5 AND l.last_name_prefix5 = r.last_name_prefix5",
                "exclusive_pair_count": 1,
                "cumulative_pair_count": 4,
                "max_block_size": 2,
            },
        ]

    monkeypatch.setattr(harness, "open_bounded_duckdb_connection", fake_open_connection)
    monkeypatch.setattr(harness, "count_blocked_pairs", fake_count_blocked_pairs)


def _assert_known_answer_benchmark_observation(
    receipt: dict[str, Any],
    *,
    input_path: Path,
    temp_root: Path,
) -> None:
    observation = receipt["observations"][0]
    assert observation["elapsed_seconds"] >= 0
    assert observation["peak_rss_bytes"] >= 0
    assert observation["peak_temp_bytes"] >= 0
    assert isinstance(observation["benchmark_invocation_id"], str)
    assert observation["benchmark_invocation_id"]
    observation["elapsed_seconds"] = 0.0
    observation["peak_rss_bytes"] = 0
    observation["peak_temp_bytes"] = 0
    observation["benchmark_invocation_id"] = "test-invocation"
    assert receipt["rows_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert observation == {
        "command": "benchmark",
        "input_rows": 4,
        "output_rows": 1,
        "cohort_size": 10,
        "timeout_seconds": 30,
        "memory_bytes": 67108864,
        "temp_bytes": 67108864,
        "temp_root": str(temp_root),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "unique_signature_count": 3,
        "null_counts": {
            "canonical_name": 0,
            "employer": 1,
            "occupation": 2,
            "city": 2,
            "state": 0,
            "zip5": 0,
        },
        "blocking_rules": [
            {
                "rule_index": 0,
                "blocking_rule": "l.last_name = r.last_name AND l.state = r.state",
                "exclusive_pair_count": 3,
                "cumulative_pair_count": 3,
                "max_block_size": 3,
            },
            {
                "rule_index": 1,
                "blocking_rule": "l.zip5 = r.zip5 AND l.last_name_prefix5 = r.last_name_prefix5",
                "exclusive_pair_count": 1,
                "cumulative_pair_count": 4,
                "max_block_size": 2,
            },
        ],
        "max_block_size": 3,
        "elapsed_seconds": 0.0,
        "peak_rss_bytes": 0,
        "peak_temp_bytes": 0,
        "exit_state": "passed",
        "benchmark_invocation_id": "test-invocation",
    }


def _assert_known_answer_er_rows(calls: dict[str, object]) -> None:
    assert calls["entity_type"] == "person"
    assert calls["closed"] is True
    assert calls["bounded_connection"] is not None
    assert [row["id"] for row in calls["er_rows"]] == ["a", "b", "c", "c"]
    assert calls["er_rows"][0] == {
        "id": "a",
        "canonical_name": "JOHN SMITH",
        "first_name": "JOHN",
        "last_name": "SMITH",
        "last_name_prefix5": "SMITH",
        "last_name_prefix3": "SMI",
        "date_of_birth": None,
        "normalized_address": None,
        "street_number": None,
        "zip5": "27601",
        "state": "NC",
        "employer": None,
        "occupation": "LAWYER",
        "identifier_key": None,
    }


def test_benchmark_observations_are_hand_calculated_and_deterministically_ordered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    output_path = temp_root / "receipt.json"
    _write_normalized_jsonl(input_path, _known_answer_benchmark_rows(harness))
    calls: dict[str, object] = {}
    _patch_known_answer_blocking(monkeypatch, harness, calls)

    assert (
        harness._benchmark(_benchmark_child_args(tmp_path, input_path=str(input_path), output_path=str(output_path)))
        == 0
    )

    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    _assert_known_answer_benchmark_observation(receipt, input_path=input_path, temp_root=temp_root)
    _assert_known_answer_er_rows(calls)
    assert "benchmark input_rows=4 unique_signatures=3 max_block_size=3 exit_state=passed" in capsys.readouterr().out


def test_benchmark_subprocess_timeout_writes_red_observation_and_terminates_exact_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    output_path = temp_root / "receipt.json"
    events: list[object] = []

    class FakeProcess:
        pid = 43210
        returncode = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append(("terminate", self.pid))
            self.returncode = -15

        def kill(self) -> None:
            events.append(("kill", self.pid))
            self.returncode = -9

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            events.append(("communicate", timeout))
            return ("", "")

    monkeypatch.setattr(
        harness.subprocess, "Popen", lambda *args, **kwargs: events.append(("popen", args, kwargs)) or FakeProcess()
    )
    monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 31.0]).__next__)
    monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
    monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

    assert (
        harness._benchmark(
            _benchmark_args(tmp_path, input_path=str(input_path), output_path=str(output_path), timeout_seconds=30)
        )
        == 1
    )

    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    observation = receipt.observations[0]
    assert observation.exit_state == "timeout"
    assert observation.input_sha256 == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert observation.peak_rss_bytes == 0
    assert observation.peak_temp_bytes == 0
    assert ("terminate", 43210) in events
    assert all(event[0] != "kill" for event in events)


def test_benchmark_subprocess_memory_and_temp_overruns_write_red_observations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])

    class FakeProcess:
        pid = 54321
        returncode = None

        def poll(self) -> None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "")

    def run_case(kind: str, output_name: str) -> str:
        process = FakeProcess()
        monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: process)
        monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
        monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 33 if kind == "memory" else 0)
        monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 44 if kind == "temp" else 0)
        output_path = temp_root / output_name

        result = harness._benchmark(
            _benchmark_args(
                tmp_path,
                input_path=str(input_path),
                output_path=str(output_path),
                memory_bytes=32,
                temp_bytes=43,
            )
        )

        assert result == 1
        receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
        return receipt.observations[0].exit_state

    assert run_case("memory", "memory.json") == "memory_exceeded"
    assert run_case("temp", "temp.json") == "temp_exceeded"


def test_benchmark_subprocess_nonzero_exit_without_receipt_writes_red_failed_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    output_path = temp_root / "receipt.json"

    class FakeProcess:
        pid = 24680
        returncode = 3

        def poll(self) -> int:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "boom")

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
    monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
    monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

    result = harness._benchmark(_benchmark_args(tmp_path, input_path=str(input_path), output_path=str(output_path)))

    assert result == 1
    assert output_path.is_file()
    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    observation = receipt.observations[0]
    assert observation.exit_state == "failed"
    assert observation.output_rows == 0
    assert observation.input_sha256 == hashlib.sha256(input_path.read_bytes()).hexdigest()


def test_benchmark_subprocess_zero_exit_cannot_reuse_stale_passed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    output_path = temp_root / "receipt.json"
    args = _benchmark_args(
        tmp_path,
        input_path=str(input_path),
        output_path=str(output_path),
    )
    stale_receipt = _passed_benchmark_receipt(harness, args)
    output_path.write_text(stale_receipt.model_dump_json() + "\n", encoding="utf-8")

    class FakeProcess:
        pid = 97531
        returncode = 0

        def poll(self) -> int:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "")

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
    monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
    monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

    result = harness._benchmark(args)

    assert result == 1
    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert receipt.observations[0].exit_state == "failed"
    assert receipt.observations[0].output_rows == 0


def test_benchmark_subprocess_zero_exit_rejects_concurrently_recreated_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    output_path = temp_root / "receipt.json"
    args = _benchmark_args(
        tmp_path,
        input_path=str(input_path),
        output_path=str(output_path),
    )
    stale_receipt = _passed_benchmark_receipt(harness, args)

    class FakeProcess:
        pid = 97532
        returncode = 0

        def poll(self) -> int:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "")

    def launch_child(*_args: object, **_kwargs: object) -> FakeProcess:
        output_path.write_text(stale_receipt.model_dump_json() + "\n", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(harness.subprocess, "Popen", launch_child)
    monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
    monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
    monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

    result = harness._benchmark(args)

    assert result == 1
    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert receipt.observations[0].exit_state == "failed"
    assert receipt.observations[0].output_rows == 0


def test_benchmark_invocation_id_is_safe_as_a_separate_cli_argument() -> None:
    harness = _load_harness()

    benchmark_invocation_id = harness._new_benchmark_invocation_id()

    assert len(benchmark_invocation_id) == 64
    assert set(benchmark_invocation_id) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "mutation",
    [
        ("receipt", "rows_sha256", "0" * 64),
        ("observation", "input_sha256", "0" * 64),
        ("observation", "cohort_size", 9),
        ("observation", "timeout_seconds", 29),
        ("observation", "memory_bytes", 1024),
        ("observation", "temp_bytes", 2048),
        ("observation", "temp_root", "/tmp/not-the-requested-root"),
    ],
)
def test_benchmark_subprocess_rejects_receipt_evidence_from_another_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: tuple[str, str, object],
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    output_path = temp_root / "receipt.json"
    args = _benchmark_args(
        tmp_path,
        input_path=str(input_path),
        output_path=str(output_path),
    )
    target, field_name, wrong_value = mutation

    class FakeProcess:
        pid = 86420
        returncode = 0

        def poll(self) -> int:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "")

    def launch_child(argv: list[str], *_args: object, **_kwargs: object) -> FakeProcess:
        child_receipt = _passed_benchmark_receipt(
            harness,
            args,
            benchmark_invocation_id=_benchmark_invocation_id_from_child_argv(argv),
        )
        if target == "receipt":
            child_receipt = child_receipt.model_copy(update={field_name: wrong_value})
        else:
            observation = child_receipt.observations[0].model_copy(update={field_name: wrong_value})
            child_receipt = child_receipt.model_copy(update={"observations": (observation,)})
        output_path.write_text(child_receipt.model_dump_json() + "\n", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(harness.subprocess, "Popen", launch_child)
    monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
    monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
    monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

    result = harness._benchmark(args)

    assert result == 1
    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert receipt.observations[0].exit_state == "failed"


def test_benchmark_subprocess_zero_exit_over_budget_receipt_writes_red_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])

    class FakeProcess:
        pid = 13579
        returncode = 0

        def poll(self) -> int:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return ("", "")

    def run_case(output_name: str, over_rss: int, over_temp: int) -> Any:
        output_path = temp_root / output_name
        args = _benchmark_args(
            tmp_path,
            input_path=str(input_path),
            output_path=str(output_path),
            memory_bytes=32,
            temp_bytes=43,
        )

        def launch_child(argv: list[str], *_args: object, **_kwargs: object) -> FakeProcess:
            child_receipt = _passed_benchmark_receipt(
                harness,
                args,
                benchmark_invocation_id=_benchmark_invocation_id_from_child_argv(argv),
            )
            observation = child_receipt.observations[0].model_copy(
                update={"peak_rss_bytes": over_rss, "peak_temp_bytes": over_temp}
            )
            child_receipt = child_receipt.model_copy(update={"observations": (observation,)})
            output_path.write_text(child_receipt.model_dump_json() + "\n", encoding="utf-8")
            return FakeProcess()

        monkeypatch.setattr(harness.subprocess, "Popen", launch_child)
        monkeypatch.setattr(harness.time, "monotonic", iter([0.0, 0.1]).__next__)
        monkeypatch.setattr(harness, "_child_rss_bytes", lambda _pid: 0)
        monkeypatch.setattr(harness, "_temp_tree_size_bytes", lambda _path: 0)

        result = harness._benchmark(args)

        assert result == 1
        receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
        return receipt.observations[0]

    memory_observation = run_case("memory.json", over_rss=64, over_temp=0)
    assert memory_observation.exit_state == "memory_exceeded"
    assert memory_observation.peak_rss_bytes == 64

    temp_observation = run_case("temp.json", over_rss=0, over_temp=99)
    assert temp_observation.exit_state == "temp_exceeded"
    assert temp_observation.peak_temp_bytes == 99


def test_benchmark_duckdb_boundaries_fail_before_rows_are_processed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(
        input_path,
        [
            harness.NormalizedBenchmarkRow(
                row_id="a",
                canonical_name="DOE, JANE",
                employer=None,
                occupation=None,
                city=None,
                state="NC",
                zip5="27601",
            )
        ],
    )
    monkeypatch.setattr(
        harness,
        "_read_normalized_benchmark_jsonl",
        lambda _path: (_ for _ in ()).throw(AssertionError("input rows must not be processed")),
    )

    with pytest.raises(ValueError, match=r"default \.tmp"):
        dot_tmp = temp_root / ".tmp"
        dot_tmp.mkdir()
        dot_tmp_input = dot_tmp / "normalized_rows.jsonl"
        _write_normalized_jsonl(dot_tmp_input, [])
        harness._benchmark(
            _benchmark_child_args(
                tmp_path,
                temp_root=str(dot_tmp),
                input_path=str(dot_tmp_input),
                output_path=str(dot_tmp / "receipt.json"),
            )
        )

    with pytest.raises(ValueError, match="output-path"):
        harness._benchmark(
            _benchmark_child_args(
                tmp_path,
                input_path=str(input_path),
                output_path=str(tmp_path / "outside.json"),
            )
        )


def _donor_proxy_owner_spy_data() -> dict[str, object]:
    db_rows: list[dict[str, object]] = [
        {
            "id": f"donor-{index:03d}",
            "canonical_name": "DOE, JANE",
            "contributor_name_raw": "DOE, JANE",
            "contributor_employer": "ACME",
            "contributor_occupation": "ENGINEER",
            "contributor_city": "RALEIGH",
            "contributor_state": "NC",
            "contributor_zip": "276011234",
            "zip5": "27601",
            "transaction_count": index,
        }
        for index in range(130)
    ]
    scored = [
        {
            "entity_id_a": "donor-001",
            "entity_id_b": "donor-002",
            "confidence": 0.97,
            "decided_by": "splink_v1",
            "decision_method": "probabilistic",
        }
    ]
    classified = [{**scored[0], "decision": "match"}]
    clustered = {
        "auto_merge_clusters": [
            {
                "member_ids": ["donor-001", "donor-002"],
                "canonical_entity_id": "donor-001",
                "min_confidence": 0.97,
                "min_decision": "match",
            }
        ],
        "review_components": [],
        "pairwise_decisions": classified,
    }
    return {"db_rows": db_rows, "scored": scored, "classified": classified, "clustered": clustered}


def _patch_donor_proxy_owner_spies(
    monkeypatch: pytest.MonkeyPatch,
    harness: Any,
    events: list[tuple[str, object]],
) -> dict[str, object]:
    spy_data = _donor_proxy_owner_spy_data()

    class FakeConnection:
        def __enter__(self) -> object:
            events.append(("connection_enter", None))
            return self

        def __exit__(self, *_exc: object) -> None:
            events.append(("connection_exit", None))

    conn = FakeConnection()
    monkeypatch.setattr(harness, "get_connection", lambda: events.append(("get_connection", None)) or conn)

    def extract(fake_conn: object, *, scope: dict[str, object]) -> list[dict[str, object]]:
        events.append(("extract", (fake_conn, scope)))
        return spy_data["db_rows"]

    def count(rows: list[dict[str, object]], entity_type: str, **kwargs: object) -> list[dict[str, object]]:
        events.append(("count", (rows, entity_type, sorted(kwargs))))
        return [{"rule_index": 0, "exclusive_pair_count": 4, "cumulative_pair_count": 4, "max_block_size": 2}]

    def score(rows: list[dict[str, object]], entity_type: str, **kwargs: object) -> list[dict[str, object]]:
        events.append(("score", (rows, entity_type, sorted(kwargs))))
        return spy_data["scored"]

    def classify(pairs: list[dict[str, object]]) -> list[dict[str, object]]:
        events.append(("classify", pairs))
        return spy_data["classified"]

    def cluster(pairs: list[dict[str, object]], rows: list[dict[str, object]]) -> dict[str, object]:
        events.append(("cluster", (pairs, rows)))
        return spy_data["clustered"]

    def persist_decisions(fake_conn: object, pairs: list[dict[str, object]], entity_type: str) -> list[str]:
        events.append(("persist_decisions", (fake_conn, pairs, entity_type)))
        return ["decision-id"]

    def persist_clusters(fake_conn: object, clusters: list[dict[str, object]], entity_type: str) -> list[str]:
        events.append(("persist_clusters", (fake_conn, clusters, entity_type)))
        return ["cluster-id"]

    monkeypatch.setattr(harness, "extract_donors_for_matching", extract)
    monkeypatch.setattr(harness, "count_blocked_pairs", count)
    monkeypatch.setattr(harness, "score_rows", score)
    monkeypatch.setattr(harness, "classify_scored_pairs", classify)
    monkeypatch.setattr(harness, "cluster_scored_pairs", cluster)
    monkeypatch.setattr(harness, "persist_match_decisions", persist_decisions)
    monkeypatch.setattr(harness, "persist_auto_merge_clusters", persist_clusters)
    monkeypatch.setattr(harness, "_current_process_peak_rss_bytes", lambda: 2048)
    return {"conn": conn, "classified": spy_data["classified"], "clustered": spy_data["clustered"]}


def test_donor_proxy_db_path_calls_existing_er_owners_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    events: list[tuple[str, object]] = []
    fixtures = _patch_donor_proxy_owner_spies(monkeypatch, harness, events)

    result = harness._donor_proxy(_donor_proxy_args(tmp_path))

    assert result == 0
    assert [event[0] for event in events] == [
        "get_connection",
        "connection_enter",
        "extract",
        "count",
        "score",
        "classify",
        "cluster",
        "persist_decisions",
        "persist_clusters",
        "connection_exit",
    ]
    committee_ids = [UUID("00000000-0000-0000-0000-000000000001"), UUID("00000000-0000-0000-0000-000000000002")]
    assert events[2][1] == (fixtures["conn"], {"committee_ids": committee_ids})
    assert events[3][1][1] == "person"
    assert len(events[3][1][0]) == 125
    assert events[4][1][1] == "person"
    assert events[3][1][0][0] == {
        "id": "donor-041",
        "canonical_name": "JANE DOE",
        "first_name": "JANE",
        "last_name": "DOE",
        "last_name_prefix5": "DOE",
        "last_name_prefix3": "DOE",
        "date_of_birth": None,
        "normalized_address": None,
        "street_number": None,
        "zip5": "27601",
        "state": "NC",
        "employer": "ACME",
        "occupation": "ENGINEER",
        "identifier_key": None,
    }
    assert events[7][1] == (fixtures["conn"], fixtures["classified"], "donor_identity")
    clustered = fixtures["clustered"]
    assert events[8][1] == (fixtures["conn"], clustered["auto_merge_clusters"], "donor_identity")


def test_donor_proxy_attribution_output_option_is_contained_in_temp_root(tmp_path: Path) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    parser = harness.build_argument_parser()
    donor_proxy_arguments = _without_option(DONOR_PROXY_ARGUMENTS, "--temp-root") + ["--temp-root", str(temp_root)]

    args = parser.parse_args(
        donor_proxy_arguments
        + [
            "--attribution-output-path",
            str(temp_root / "pair_attribution.json"),
        ]
    )
    paths = harness._resolve_donor_proxy_paths(args)

    assert paths.attribution_output_path == temp_root / "pair_attribution.json"

    with pytest.raises(ValueError, match="attribution-output-path"):
        harness._resolve_donor_proxy_paths(
            parser.parse_args(
                donor_proxy_arguments
                + [
                    "--attribution-output-path",
                    str(tmp_path / "outside.json"),
                ]
            )
        )
    with pytest.raises(ValueError, match="differ from output-path"):
        harness._resolve_donor_proxy_paths(
            parser.parse_args(
                donor_proxy_arguments
                + [
                    "--attribution-output-path",
                    str(temp_root / "donor_proxy_receipt.md"),
                ]
            )
        )


def test_donor_proxy_attribution_output_writes_json_without_widening_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    events: list[tuple[str, object]] = []
    fixtures = _patch_donor_proxy_owner_spies(monkeypatch, harness, events)
    attribution_path = tmp_path / "lane" / "pair_attribution.json"
    diagnostic_pairs = [
        {
            **fixtures["classified"][0],
            "match_key": 0,
            "match_weight": 8.5,
            "match_" + "probability": 0.97,
            "gamma_name": 2,
            "bf_name": 64.0,
        }
    ]

    def score_diagnostics(rows: list[dict[str, object]], entity_type: str, **kwargs: object) -> list[dict[str, object]]:
        events.append(("diagnostic_score", (rows, entity_type, kwargs)))
        return diagnostic_pairs

    monkeypatch.setattr(harness, "score_diagnostic_rows", score_diagnostics)
    monkeypatch.setattr(
        harness,
        "describe_blocking_rules",
        lambda entity_type: [{"rule_index": 0, "blocking_rule": "readable rule zero"}],
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object()])

    result = harness._donor_proxy(
        _donor_proxy_args(
            tmp_path,
            attribution_output_path=str(attribution_path),
        )
    )

    assert result == 0
    assert attribution_path.exists()
    assert json.loads(attribution_path.read_text(encoding="utf-8")) == {
        "schema_version": "donor_er_pair_attribution.v1",
        "pairs": [
            {
                "entity_id_a": "donor-001",
                "entity_id_b": "donor-002",
                "match_key": 0,
                "blocking_rule_sql": "readable rule zero",
                "match_weight": 8.5,
                "match_" + "probability": 0.97,
                "comparison_fields": [
                    {"field_name": "gamma_name", "value": 2},
                    {"field_name": "bf_name", "value": 64.0},
                ],
            }
        ],
    }
    diagnostic_events = [event for event in events if event[0] == "diagnostic_score"]
    assert len(diagnostic_events) == 1
    assert callable(diagnostic_events[0][1][2]["bounded_connection_factory"])
    persist_events = [event for event in events if event[0] == "persist_decisions"]
    assert persist_events == [("persist_decisions", (fixtures["conn"], fixtures["classified"], "donor_identity"))]
    assert set(persist_events[0][1][1][0]) == {
        "entity_id_a",
        "entity_id_b",
        "confidence",
        "decided_by",
        "decision_method",
        "decision",
    }


def test_donor_proxy_attribution_uses_receipt_cluster_sample(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    events: list[tuple[str, object]] = []
    fixtures = _patch_donor_proxy_owner_spies(monkeypatch, harness, events)
    fixtures["clustered"]["review_components"] = [
        {
            "member_ids": ["donor-003", "donor-004"],
            "min_confidence": 0.82,
            "min_decision": "possible_match",
        }
    ]
    diagnostic_pairs = [
        {
            "entity_id_a": "donor-003",
            "entity_id_b": "donor-004",
            "confidence": 0.82,
            "decided_by": "splink_v1",
            "decision_method": "probabilistic",
            "match_key": 0,
            "match_weight": 5.25,
            "match_" + "probability": 0.82,
            "gamma_name": 1,
            "bf_name": 12.5,
        }
    ]

    monkeypatch.setattr(harness, "score_diagnostic_rows", lambda *_args, **_kwargs: diagnostic_pairs)
    monkeypatch.setattr(
        harness,
        "describe_blocking_rules",
        lambda entity_type: [{"rule_index": 0, "blocking_rule": "readable rule zero"}],
    )
    monkeypatch.setattr(harness, "get_blocking_rule_sqls", lambda entity_type: [object()])

    result = harness._donor_proxy(
        _donor_proxy_args(
            tmp_path,
            attribution_output_path=str(tmp_path / "lane" / "pair_attribution.json"),
            cluster_sample_size=1,
            seed="stage-2-seed",
        )
    )

    assert result == 0
    receipt = harness.validate_donor_proxy_measurement_receipt_markdown(
        (tmp_path / "lane" / "donor_proxy_receipt.md").read_text(encoding="utf-8")
    )
    artifact = json.loads((tmp_path / "lane" / "pair_attribution.json").read_text(encoding="utf-8"))
    assert receipt.deterministic_cluster_sample == [
        {
            "member_ids": ["donor-003", "donor-004"],
            "min_confidence": 0.82,
            "min_decision": "possible_match",
        }
    ]
    assert [(pair["entity_id_a"], pair["entity_id_b"]) for pair in artifact["pairs"]] == [("donor-003", "donor-004")]


def test_benchmark_path_never_opens_db_or_persists_while_donor_proxy_is_the_persistence_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    persistence_events: list[str] = []

    monkeypatch.setattr(harness, "get_connection", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    monkeypatch.setattr(harness, "persist_match_decisions", lambda *args: persistence_events.append("decisions"))
    monkeypatch.setattr(harness, "persist_auto_merge_clusters", lambda *args: persistence_events.append("clusters"))
    monkeypatch.setattr(harness, "count_blocked_pairs", lambda *args, **kwargs: [])

    assert harness._benchmark(_benchmark_child_args(tmp_path, input_path=str(input_path))) == 0
    assert persistence_events == []

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(harness, "get_connection", lambda: FakeConnection())
    monkeypatch.setattr(harness, "extract_donors_for_matching", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(harness, "score_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(harness, "classify_scored_pairs", lambda pairs: pairs)
    monkeypatch.setattr(
        harness,
        "cluster_scored_pairs",
        lambda *_args, **_kwargs: {"auto_merge_clusters": [], "review_components": [], "pairwise_decisions": []},
    )

    assert harness._donor_proxy(_donor_proxy_args(tmp_path, slice_size=125)) == 0
    assert persistence_events == ["decisions", "clusters"]


def test_deterministic_db_prefix_and_cluster_sample_use_sha256_seeded_keys() -> None:
    harness = _load_harness()
    rows = [{"id": f"donor-{index:03d}"} for index in range(150)]
    expected_prefix = sorted(
        rows,
        key=lambda row: (
            hashlib.sha256(f"db-prefix-seed\x00{row['id']}".encode("utf-8")).hexdigest(),
            row["id"],
        ),
    )[:101]

    selected = harness.select_deterministic_db_prefix(rows, seed="db-prefix-seed", size=101)

    assert selected == expected_prefix
    assert len(selected) == 101
    assert harness._MAX_COHORT_SIZE == 100

    clusters = [
        {"cluster_id": "cluster-c", "member_ids": ["donor-003", "donor-004"]},
        {"cluster_id": "cluster-a", "member_ids": ["donor-001", "donor-002"]},
        {"member_ids": {"donor-006", "donor-005"}},
    ]
    expected_clusters = sorted(
        clusters,
        key=lambda cluster: (
            hashlib.sha256(
                f"cluster-sample-seed\x00{cluster.get('cluster_id') or 'donor-005|donor-006'}".encode("utf-8")
            ).hexdigest(),
            cluster.get("cluster_id") or "donor-005|donor-006",
        ),
    )[:2]
    expected_clusters = [{**cluster, "member_ids": sorted(cluster["member_ids"])} for cluster in expected_clusters]

    assert (
        harness.select_deterministic_cluster_sample(clusters, seed="cluster-sample-seed", size=2) == expected_clusters
    )


def _donor_proxy_receipt_kwargs() -> dict[str, object]:
    return {
        "schema_version": "donor_er_proxy_measurement.v1",
        "verdict": "SCALE_NOW",
        "donor_denominator": 100,
        "cluster_count": 40,
        "compression_ratio": 2.5,
        "cluster_size_distribution": {"1": 10, "2": 30},
        "confidence_band_counts": {"match": 96, "probable_match": 2, "possible_match": 1, "no_match": 1},
        "blocking_rule_selectivity": [{"rule_index": 0, "exclusive_pair_count": 9}],
        "chosen_slice_size": 125,
        "timing_seconds": 1.25,
        "peak_child_rss_bytes": 4096,
        "db_counts": {"extracted_donors": 150, "selected_donors": 125},
        "seed": "stage-2-seed",
        "precision_successes": 96,
        "precision_denominator": 100,
        "precision_wilson_low": 0.901629,
        "precision_wilson_high": 0.984337,
        "undecidable_count": 0,
        "deterministic_cluster_sample": [{"cluster_id": "cluster-a", "member_ids": ["donor-001", "donor-002"]}],
        "named_transaction_write_defect": None,
    }


def test_wilson_interval_and_verdict_precedence_are_known_answers() -> None:
    harness = _load_harness()

    assert harness.wilson_95_interval(successes=96, denominator=100) == pytest.approx((0.901629, 0.984337))
    assert harness.wilson_95_interval(successes=0, denominator=10) == pytest.approx((0.0, 0.277533))
    assert (
        harness.choose_scale_verdict(
            named_transaction_write_defect={"owner": "core/entity_resolution/persist.py"},
            denominator=100,
            undecidable_count=0,
            precision_lower_bound=0.99,
            minimum_precision=0.95,
        )
        == "BLOCKED_ON_NAMED_DEFECT"
    )
    assert (
        harness.choose_scale_verdict(
            named_transaction_write_defect=None,
            denominator=0,
            undecidable_count=0,
            precision_lower_bound=1.0,
            minimum_precision=0.95,
        )
        == "PRECISION_INSUFFICIENT"
    )
    assert (
        harness.choose_scale_verdict(
            named_transaction_write_defect=None,
            denominator=100,
            undecidable_count=1,
            precision_lower_bound=0.99,
            minimum_precision=0.95,
        )
        == "SCALE_WITH_CHANGES"
    )
    assert (
        harness.choose_scale_verdict(
            named_transaction_write_defect=None,
            denominator=100,
            undecidable_count=0,
            precision_lower_bound=0.99,
            minimum_precision=0.95,
        )
        == "SCALE_NOW"
    )


def test_proxy_receipt_validation_requires_single_verdict_and_evidence() -> None:
    harness = _load_harness()
    receipt = harness.DonorProxyMeasurementReceipt(**_donor_proxy_receipt_kwargs())
    markdown = harness.format_donor_proxy_measurement_receipt(receipt)

    assert markdown.startswith("## VERDICT: SCALE_NOW\n\n```donor_er_proxy_measurement_receipt\n")
    assert harness.validate_donor_proxy_measurement_receipt_markdown(markdown) == receipt

    payload = json.loads(receipt.model_dump_json())
    for missing in ("precision_denominator", "donor_denominator", "undecidable_count", "seed"):
        invalid = dict(payload)
        invalid.pop(missing)
        invalid_markdown = (
            f"## VERDICT: SCALE_NOW\n\n```donor_er_proxy_measurement_receipt\n{json.dumps(invalid)}\n```\n"
        )
        with pytest.raises(ValueError, match=missing):
            harness.validate_donor_proxy_measurement_receipt_markdown(invalid_markdown)

    with pytest.raises(ValueError, match="exactly one verdict heading"):
        harness.validate_donor_proxy_measurement_receipt_markdown(markdown.replace("## VERDICT: SCALE_NOW\n\n", ""))
    with pytest.raises(ValueError, match="exactly one verdict heading"):
        harness.validate_donor_proxy_measurement_receipt_markdown(markdown + "\n## VERDICT: SCALE_NOW\n")


def test_validate_receipt_cli_accepts_donor_proxy_measurement_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    receipt = harness.DonorProxyMeasurementReceipt(**_donor_proxy_receipt_kwargs())
    receipt_path = tmp_path / "donor_proxy_receipt.md"
    receipt_path.write_text(harness.format_donor_proxy_measurement_receipt(receipt), encoding="utf-8")

    assert harness.main(["validate-receipt", "--receipt", str(receipt_path)]) == 0
    assert (
        capsys.readouterr().out == "validate-receipt schema_version=donor_er_proxy_measurement.v1 verdict=SCALE_NOW\n"
    )

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt",
                str(receipt_path),
                "--emit-validated-json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(receipt.model_dump_json())

    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt",
                str(receipt_path),
                "--require-cleanup",
            ]
        )
        == 1
    )
    assert "cleanup evidence is not part of donor proxy measurement receipts" in capsys.readouterr().err

    payload = json.loads(receipt.model_dump_json())
    payload["seed"] = "PGPASSWORD=super-secret-token-5150"
    leaky_receipt_path = tmp_path / "leaky_donor_proxy_receipt.md"
    leaky_receipt_path.write_text(
        f"## VERDICT: SCALE_NOW\n\n```donor_er_proxy_measurement_receipt\n{json.dumps(payload)}\n```\n",
        encoding="utf-8",
    )
    assert (
        harness.main(
            [
                "validate-receipt",
                "--receipt",
                str(leaky_receipt_path),
                "--emit-validated-json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "super-secret-token-5150" not in captured.err


def test_benchmark_in_process_path_stays_offline_and_avoids_persistence_imports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])

    def deny_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("benchmark must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", deny_socket)
    monkeypatch.setattr(harness, "count_blocked_pairs", lambda *args, **kwargs: [])
    forbidden_modules = {"core.db", "core.graph", "core.entity_resolution.persist"}
    imported_before = set(sys.modules)

    assert harness._benchmark(_benchmark_child_args(tmp_path, input_path=str(input_path))) == 0
    assert not ((set(sys.modules) - imported_before) & forbidden_modules)


def test_benchmark_cli_child_uses_fresh_interpreter_offline_hooks(tmp_path: Path) -> None:
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    output_path = temp_root / "receipt.json"
    sentinel_path = tmp_path / "sitecustomize_sentinel"
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "\n".join(
            [
                "import pathlib, socket",
                f"pathlib.Path({str(sentinel_path)!r}).write_text('loaded', encoding='utf-8')",
                "def deny_connect(self, *args, **kwargs):",
                "    raise AssertionError('network denied by sitecustomize')",
                "socket.socket.connect = deny_connect",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    harness = _load_harness()
    rows = [
        harness.NormalizedBenchmarkRow(
            row_id="a",
            canonical_name="DOE, JANE",
            employer="ACME",
            occupation="ENGINEER",
            city="RALEIGH",
            state="NC",
            zip5="27601",
        ),
        harness.NormalizedBenchmarkRow(
            row_id="b",
            canonical_name="DOE, JOHN",
            employer="OTHER",
            occupation="TEACHER",
            city="DURHAM",
            state="NC",
            zip5="27701",
        ),
    ]
    _write_normalized_jsonl(input_path, rows)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["DATABASE_URL"] = "postgresql://should-be-scrubbed.invalid/db"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/donor_er_scale_spike.py",
            "benchmark",
            "--input-path",
            str(input_path),
            "--output-path",
            str(output_path),
            "--cohort-size",
            "2",
            "--timeout-seconds",
            "30",
            "--memory-bytes",
            str(1024 * 1024 * 1024),
            "--temp-bytes",
            str(1024 * 1024 * 1024),
            "--temp-root",
            str(temp_root),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert sentinel_path.read_text(encoding="utf-8") == "loaded"
    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    observation = receipt.observations[0]
    assert observation.input_rows == 2
    assert observation.unique_signature_count == 2
    assert [
        (
            rule["exclusive_pair_count"],
            rule["cumulative_pair_count"],
            rule["max_block_size"],
        )
        for rule in observation.blocking_rules or []
    ] == [
        (1, 1, 4),
        (0, 1, 1),
        (0, 1, 0),
        (0, 1, 0),
        (0, 1, 0),
    ]
    assert observation.max_block_size == 4
    assert observation.exit_state == "passed"
    assert "benchmark input_rows=2 unique_signatures=2 max_block_size=4" in completed.stdout


def test_benchmark_cli_writes_receipt_and_concise_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    output_path = temp_root / "receipt.json"
    _write_normalized_jsonl(
        input_path,
        [
            harness.NormalizedBenchmarkRow(
                row_id="a",
                canonical_name="DOE, JANE",
                employer="ACME",
                occupation="ENGINEER",
                city="RALEIGH",
                state="NC",
                zip5="27601",
            )
        ],
    )

    assert (
        harness.main(
            [
                "benchmark",
                "--input-path",
                str(input_path),
                "--output-path",
                str(output_path),
                "--cohort-size",
                "1",
                "--timeout-seconds",
                "30",
                "--memory-bytes",
                str(1024 * 1024 * 1024),
                "--temp-bytes",
                str(1024 * 1024 * 1024),
                "--temp-root",
                str(temp_root),
            ]
        )
        == 0
    )

    receipt = harness.DonorErScaleSpikeReceipt.model_validate_json(output_path.read_text(encoding="utf-8"))
    observation = receipt.observations[0]
    assert observation.input_rows == 1
    assert observation.output_rows == 1
    assert observation.exit_state == "passed"
    assert "benchmark input_rows=1 unique_signatures=1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_path", "https://example.invalid/rows.jsonl", "network"),
        ("input_path", "postgresql://localhost/civibus", "database"),
        ("output_path", "fly://app/tmp/receipt.json", "Fly"),
        ("output_path", "outside", "output-path"),
        ("cohort_size", 101, "cohort-size"),
    ],
)
def test_benchmark_rejects_unsafe_cli_boundaries_before_subprocess_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    if value == "outside":
        value = str(tmp_path / "outside.json")
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("benchmark child must not launch")),
    )
    overrides = {field: value}
    if field != "input_path":
        overrides["input_path"] = str(input_path)

    with pytest.raises(ValueError, match=message):
        harness._benchmark(_benchmark_args(tmp_path, **overrides))


def test_rejected_output_paths_do_not_create_outside_parent_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    outside_parent = tmp_path / "outside" / "nested"
    outside_output = outside_parent / "receipt.json"
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("benchmark child must not launch")),
    )
    monkeypatch.setattr(
        harness,
        "get_connection",
        lambda: (_ for _ in ()).throw(AssertionError("donor proxy must not open DB")),
    )

    with pytest.raises(ValueError, match="output-path"):
        harness._benchmark(
            _benchmark_args(
                tmp_path,
                input_path=str(input_path),
                output_path=str(outside_output),
            )
        )
    with pytest.raises(ValueError, match="output-path"):
        harness._donor_proxy(_donor_proxy_args(tmp_path, output_path=str(outside_output)))

    assert not outside_parent.exists()


def test_benchmark_rejects_output_aliasing_input_without_changing_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    temp_root = tmp_path / "lane"
    temp_root.mkdir()
    input_path = temp_root / "normalized_rows.jsonl"
    _write_normalized_jsonl(input_path, [])
    original_input = input_path.read_bytes()
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("benchmark child must not launch")),
    )

    with pytest.raises(ValueError, match="output-path.*input-path"):
        harness._benchmark(
            _benchmark_args(
                tmp_path,
                input_path=str(input_path),
                output_path=str(input_path),
            )
        )

    assert input_path.read_bytes() == original_input


def test_benchmark_rejects_repository_fec_cache_paths_before_subprocess_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    fec_bulk_files = importlib.import_module("domains.campaign_finance.ingest.fec_bulk_files")
    repo_cache_root = fec_bulk_files.fec_bulk_data_root(REPO_ROOT / "data").resolve(strict=False)
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("benchmark child must not launch")),
    )

    with pytest.raises(ValueError, match="repository FEC bulk cache"):
        harness._benchmark(_benchmark_args(tmp_path, temp_root=str(repo_cache_root)))


@pytest.mark.dev_repo_only(private_asset=".debbie.toml", owner="Debbie projection contract")
def test_debbie_projection_includes_harness_script_and_tests_mirror(tmp_path: Path) -> None:
    payload = tomllib.loads((REPO_ROOT / ".debbie.toml").read_text(encoding="utf-8"))

    assert "scripts/donor_er_scale_spike.py" in payload["sync"]["files"]
    assert any(entry["path"].rstrip("/") == "tests" for entry in payload["sync"]["dirs"])
    projected_files = {Path(path) for path in payload["sync"]["files"]}
    projected_dirs = {Path(entry["path"].rstrip("/")) for entry in payload["sync"]["dirs"]}
    assert Path("scripts/donor_er_scale_spike.py") in projected_files
    assert Path("tests") in projected_dirs
    assert Path("scripts") not in projected_dirs

    projected_mirror = project_debbie_public_mirror(tmp_path)
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--extra",
            "dev",
            "--extra",
            "entity-resolution",
            "pytest",
            "-q",
            "tests/test_donor_er_scale_spike.py::test_public_module_surface_and_cli_subcommands",
        ],
        cwd=projected_mirror.root,
        env=projected_mirror.env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, "\n".join(
        [
            f"returncode={completed.returncode}",
            "stdout:",
            completed.stdout,
            "stderr:",
            completed.stderr,
        ]
    )


# --- Stage 4 terminal MEASUREMENT_NOT_READY receipt contract -----------------
# Stage 4 publishes the pre-materialization not-ready receipt. These tests pin
# the shape that branch needs: a narrative Markdown report carrying exactly one
# fenced object, nullable cleanup roots for roots that were never created, and
# explicit zero lane PID/proxy evidence.


def _archive_identity_kwargs(cycle: int = 2024) -> dict[str, object]:
    return {
        "cycle": cycle,
        "path": f"/shared/data/fec/bulk/{cycle}/itcont{str(cycle)[-2:]}.zip",
        "size_bytes": 4244259029,
        "sha256": "6" * 64,
        "member_name": "itcont.txt",
        "crc_ok": True,
        "part_files_present": 0,
    }


def _decision_menu_kwargs() -> dict[str, object]:
    return {
        "gap_spec": [
            {
                "gap_id": "GAP-1",
                "owner": "B2 / cache acquisition",
                "closing_condition": "Re-record archive path, bytes, and SHA-256 for the current archives.",
            }
        ],
        "proxy_substituted": False,
        "proxy_offer_bias": "A narrowed slice understates the denominator and biases toward GO.",
        "conditional_disposition": ["Archive identities re-recorded with SHA-256 and accepted."],
        "rerun_menu": ["shasum -a 256 /shared/data/fec/bulk/2024/itcont24.zip"],
    }


def _not_ready_cleanup_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "data_root_path": None,
        "data_root_created": False,
        "data_root_removed": False,
        "temp_root_path": None,
        "temp_root_created": False,
        "temp_root_removed": False,
        "credential_root_path": "/tmp/civibus_donor_er_credentials/lane.x",
        "credential_root_absent": True,
        "credential_paths": [],
        "credential_files_present": 0,
        "lane_pid_count": 0,
        "lane_proxy_count": 0,
    }
    kwargs.update(overrides)
    return kwargs


def _not_ready_receipt_kwargs(harness: Any, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "schema_version": "donor_er_architecture_receipt.v1",
        "b2_disposition": "NO_GO",
        "b2_blocker_class": "COVERAGE_IDENTITY",
        "terminal_disposition": "MEASUREMENT_NOT_READY",
        "materialization_started": False,
        "b2_source": {
            "verbatim_verdict": "## VERDICT: NO-GO",
            "source_path": "docs/live-state/2026_07_24_b2_true_count_and_sizing.md:3",
        },
        "archive_identities": [_archive_identity_kwargs(cycle) for cycle in (2022, 2024, 2026)],
        "resource_locality": {
            "execution_locality": "local_macos_worktree_offline",
            "offline": True,
            "peak_rss_bytes": 0,
            "peak_temp_bytes": 0,
            "memory_budget_bytes": 12884901888,
            "temp_budget_bytes": 8589934592,
        },
        "cleanup_evidence": _not_ready_cleanup_kwargs(),
        "decision_menu": _decision_menu_kwargs(),
        "benchmark": None,
        "blocker_evidence": {
            "normalized_owner_path": "domains/campaign_finance/ingest/fec_bulk_files.py",
            "source_evidence": "2022 and 2026 archive byte counts drifted from the B2 record.",
            "normalization_reason": None,
            "rerun_command": "shasum -a 256 /shared/data/fec/bulk/2022/itcont22.zip",
            "detail": "coverage-identity blocker: archive identity drifted from the B2 reference",
        },
    }
    kwargs.update(overrides)
    return kwargs


def test_stage4_not_ready_receipt_is_accepted_by_the_receipt_oracle() -> None:
    harness = _load_harness()
    receipt = harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness))

    assert receipt.terminal_disposition == "MEASUREMENT_NOT_READY"
    assert receipt.materialization_started is False
    assert receipt.benchmark is None
    assert receipt.cleanup_evidence.lane_pid_count == 0
    assert receipt.cleanup_evidence.lane_proxy_count == 0
    assert [identity.cycle for identity in receipt.archive_identities] == [2022, 2024, 2026]
    assert receipt.decision_menu is not None
    assert receipt.decision_menu.proxy_substituted is False
    # The three pre-existing architecture literals are untouched by this stage.
    assert harness.ARCHITECTURE_DISPOSITIONS == EXPECTED_ARCHITECTURE_DISPOSITIONS


def test_not_ready_receipt_requires_decision_menu_and_forbids_started_materialization() -> None:
    harness = _load_harness()

    without_menu = _not_ready_receipt_kwargs(harness, decision_menu=None)
    with pytest.raises(ValidationError, match="decision menu"):
        harness.DonorErArchitectureReceipt(**without_menu)

    started = _not_ready_receipt_kwargs(harness, materialization_started=True)
    with pytest.raises(ValidationError, match="materialization"):
        harness.DonorErArchitectureReceipt(**started)


def test_receipt_without_materialization_cannot_carry_benchmark_observations() -> None:
    harness = _load_harness()
    kwargs = _go_receipt_kwargs(harness, materialization_started=False)
    with pytest.raises(ValidationError, match="materialization"):
        harness.DonorErArchitectureReceipt(**kwargs)


def test_cleanup_evidence_nullable_roots_track_created_removed_and_absent() -> None:
    harness = _load_harness()

    # A root that was never created has no path and cannot have been removed.
    uncreated_but_pathed = _not_ready_cleanup_kwargs(data_root_path="/tmp/civibus_donor_er/lane.x")
    with pytest.raises(ValidationError, match="not created"):
        harness.CleanupEvidence(**uncreated_but_pathed)

    uncreated_but_removed = _not_ready_cleanup_kwargs(data_root_removed=True)
    with pytest.raises(ValidationError, match="not created"):
        harness.CleanupEvidence(**uncreated_but_removed)

    created_without_path = _not_ready_cleanup_kwargs(temp_root_created=True)
    with pytest.raises(ValidationError, match="created"):
        harness.CleanupEvidence(**created_without_path)

    # A created-and-removed root is representable.
    created_and_removed = harness.CleanupEvidence(
        **_not_ready_cleanup_kwargs(
            temp_root_path="/tmp/civibus_donor_er/lane.x",
            temp_root_created=True,
            temp_root_removed=True,
        )
    )
    assert created_and_removed.temp_root_removed is True
    assert created_and_removed.data_root_path is None

    # Claiming the credential root is absent while files remain is incoherent.
    absent_with_files = _not_ready_cleanup_kwargs(credential_files_present=1)
    with pytest.raises(ValidationError, match="absent"):
        harness.CleanupEvidence(**absent_with_files)


def test_cleanup_evidence_rejects_secret_bearing_credential_root_path() -> None:
    harness = _load_harness()
    for secret in ("PGPASSWORD=super-secret-token", "postgresql://user:pass@localhost/db"):
        with pytest.raises(ValidationError):
            harness.CleanupEvidence(**_not_ready_cleanup_kwargs(credential_root_path=secret))
    for traversal_path in (
        "/tmp/civibus_donor_er_credentials/../secret-root",
        "/tmp/civibus_donor_er_credentials/lane.x/../../secret.txt",
    ):
        kwargs = _not_ready_cleanup_kwargs(credential_root_path=traversal_path, credential_root_absent=False)
        with pytest.raises(ValidationError, match="traversal"):
            harness.CleanupEvidence(**kwargs)
    with pytest.raises(ValidationError, match="traversal"):
        harness.CleanupEvidence(
            **_not_ready_cleanup_kwargs(
                credential_root_absent=False,
                credential_paths=["/tmp/civibus_donor_er_credentials/lane.x/../../secret.txt"],
            )
        )


def test_single_fenced_receipt_json_trusts_one_fence_inside_narrative(tmp_path: Path) -> None:
    harness = _load_harness()
    valid_json = harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness)).model_dump_json()

    # Surrounding narrative is allowed; only the fenced object is authoritative.
    narrative = _receipt_markdown_with_narrative(valid_json)
    assert harness._single_fenced_receipt_json(narrative) == valid_json

    accepted = _write_markdown(tmp_path / "narrative.md", narrative)
    assert harness.main(["validate-receipt", "--receipt", str(accepted)]) == 0

    # Prose is never authoritative: the fake object in the narrative says GO,
    # but the validated receipt is the fenced NO_GO object.
    assert '{"b2_disposition": "GO"}' in narrative
    receipt = harness._parse_receipt_markdown(accepted)
    assert receipt.b2_disposition == "NO_GO"

    for name, text in (
        ("zero.md", "# Report\n\nNo fence here at all.\n"),
        ("wrong_language.md", _receipt_markdown(valid_json, language="json")),
        ("multiple.md", _receipt_markdown(valid_json) + _receipt_markdown(valid_json)),
        ("multiple_in_narrative.md", _receipt_markdown_with_narrative(valid_json) + _receipt_markdown(valid_json)),
    ):
        path = _write_markdown(tmp_path / name, text)
        assert harness.main(["validate-receipt", "--receipt", str(path)]) == 1


def test_validate_receipt_accepts_receipt_flag_and_preserves_receipt_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()
    valid_json = harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness)).model_dump_json()
    receipt_path = _write_markdown(tmp_path / "receipt.md", _receipt_markdown_with_narrative(valid_json))

    for option in ("--receipt", "--receipt-path"):
        assert harness.main(["validate-receipt", option, str(receipt_path)]) == 0
        captured = capsys.readouterr()
        assert "terminal_disposition=MEASUREMENT_NOT_READY" in captured.out

    # Exactly one of the two spellings is required; neither and both-conflicting fail.
    assert harness.main(["validate-receipt"]) != 0
    capsys.readouterr()
    other = _write_markdown(tmp_path / "other.md", _receipt_markdown(valid_json))
    assert harness.main(["validate-receipt", "--receipt", str(receipt_path), "--receipt-path", str(other)]) == 1
    capsys.readouterr()
    # Naming the same file through both spellings is unambiguous and allowed.
    assert harness.main(["validate-receipt", "--receipt", str(receipt_path), "--receipt-path", str(receipt_path)]) == 0
    capsys.readouterr()


def test_validate_receipt_require_cleanup_proves_lane_resources_were_released(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _load_harness()

    clean_receipt = harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness))
    clean_json = clean_receipt.model_dump_json()
    clean_path = _write_markdown(tmp_path / "clean.md", _receipt_markdown_with_narrative(clean_json))
    assert harness.main(["validate-receipt", "--receipt", str(clean_path), "--require-cleanup"]) == 0
    assert "cleanup=verified" in capsys.readouterr().out
    # The property and the gate share one release rule; pin them to agree.
    assert clean_receipt.cleanup_evidence.lane_resources_released is True

    # Each unreleased lane resource must fail the cleanup gate on its own.
    unclean_cases = {
        "unremoved_data_root": _not_ready_cleanup_kwargs(
            data_root_path="/tmp/civibus_donor_er/lane.x",
            data_root_created=True,
            data_root_removed=False,
        ),
        "unremoved_temp_root": _not_ready_cleanup_kwargs(
            temp_root_path="/tmp/civibus_donor_er/lane.x",
            temp_root_created=True,
            temp_root_removed=False,
        ),
        "credential_root_present": _not_ready_cleanup_kwargs(credential_root_absent=False),
        "credential_files_remaining": _not_ready_cleanup_kwargs(
            credential_root_absent=False,
            credential_files_present=1,
        ),
        "live_pid": _not_ready_cleanup_kwargs(lane_pid_count=1),
        "live_proxy": _not_ready_cleanup_kwargs(lane_proxy_count=1),
    }
    for name, cleanup in unclean_cases.items():
        payload = _receipt_payload(harness, _not_ready_receipt_kwargs(harness, cleanup_evidence=cleanup))
        path = _write_markdown(tmp_path / f"{name}.md", _receipt_markdown(json.dumps(payload)))
        # The receipt itself is still valid; only the cleanup gate rejects it.
        assert harness.main(["validate-receipt", "--receipt", str(path)]) == 0
        capsys.readouterr()
        assert harness.main(["validate-receipt", "--receipt", str(path), "--require-cleanup"]) == 1, name
        assert "cleanup=verified" not in capsys.readouterr().out
        assert harness.CleanupEvidence(**cleanup).lane_resources_released is False, name


def test_receipt_owns_archive_identity_and_menu_fields_rather_than_prose() -> None:
    harness = _load_harness()
    fields = harness.DonorErArchitectureReceipt.model_fields
    assert {"materialization_started", "archive_identities", "decision_menu"} <= set(fields)
    assert harness.ArchiveIdentity.model_config["extra"] == "forbid"
    assert harness.NotReadyDecisionMenu.model_config["extra"] == "forbid"
    assert harness.ResourceLocalityEvidence.model_fields["offline"].annotation is bool

    # A not-ready receipt must carry at least one archive identity and a
    # non-empty gap spec, proxy bias, conditional disposition, and rerun menu.
    with pytest.raises(ValidationError):
        harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness, archive_identities=[]))
    for empty_field in ("gap_spec", "conditional_disposition", "rerun_menu"):
        menu = {**_decision_menu_kwargs(), empty_field: []}
        with pytest.raises(ValidationError):
            harness.DonorErArchitectureReceipt(**_not_ready_receipt_kwargs(harness, decision_menu=menu))
    for field_name, traversal_value in (
        ("path", "/shared/data/fec/bulk/2024/../shadow/itcont24.zip"),
        ("member_name", "../itcont.txt"),
    ):
        archive_identity = {**_archive_identity_kwargs(), field_name: traversal_value}
        with pytest.raises(ValidationError, match="traversal"):
            harness.DonorErArchitectureReceipt(
                **_not_ready_receipt_kwargs(harness, archive_identities=[archive_identity])
            )
