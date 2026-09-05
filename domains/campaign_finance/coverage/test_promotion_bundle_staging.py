from __future__ import annotations

import io
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from domains.campaign_finance.coverage import lifecycle
from domains.campaign_finance.coverage.test_lifecycle import _promotion_receipt_payload


INSTALL_DIRECTORY = PurePosixPath("app/private/civibus/authority-promotion")
INSTALL_PATH = Path("/") / Path(*INSTALL_DIRECTORY.parts)
RECEIPT_NAME = "authority-promotion-receipt.json"
ARCHIVE_NAME = "authority-promotion-bundle.tar"
EXPECTED_REVISION = "a" * 40
EXPECTED_RUN_ID = "123456789"
EXPECTED_RUN_NAME = "deploy.yml"
EXPECTED_ARTIFACT_NAME = "authority-promotion-bundle"
EMBEDDED_BUILD_RECEIPT = str(INSTALL_DIRECTORY / "authority-promotion-bundle-build-receipt.json")


def _stage_identity() -> dict[str, str]:
    return {
        "expected_run_id": EXPECTED_RUN_ID,
        "expected_run_name": EXPECTED_RUN_NAME,
        "expected_artifact_name": EXPECTED_ARTIFACT_NAME,
    }


def test_build_authority_promotion_bundle_is_deterministic_and_run_bound(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = _promotion_receipt_payload(source)
    receipt_path = source / RECEIPT_NAME
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()
    build_receipt_path = tmp_path / "bundle-build-receipt.json"

    archive_path = lifecycle.build_authority_promotion_bundle(
        receipt_path=receipt_path,
        artifact_directory=artifact_directory,
        build_receipt_path=build_receipt_path,
        run_id="123456789",
        run_name="deploy.yml",
        artifact_name="authority-promotion-bundle",
        expected_source_revision=EXPECTED_REVISION,
        expected_api_revision=EXPECTED_REVISION,
        expected_web_revision=EXPECTED_REVISION,
    )

    assert list(artifact_directory.iterdir()) == [archive_path]
    assert archive_path.name == ARCHIVE_NAME
    assert archive_path.stat().st_mode & 0o777 == 0o600
    build_receipt = json.loads(build_receipt_path.read_text(encoding="utf-8"))
    assert build_receipt["run_id"] == "123456789"
    assert build_receipt["run_name"] == "deploy.yml"
    assert build_receipt["artifact_name"] == "authority-promotion-bundle"
    assert build_receipt["source_revision"] == EXPECTED_REVISION
    assert build_receipt["api_revision"] == EXPECTED_REVISION
    assert build_receipt["web_revision"] == EXPECTED_REVISION
    assert build_receipt["archive_sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert all(member["mode"] == "0600" for member in build_receipt["members"])
    assert len({member["path"] for member in build_receipt["members"]}) == len(build_receipt["members"])
    assert build_receipt["embedded_build_receipt_path"] == EMBEDDED_BUILD_RECEIPT

    second_artifact_directory = tmp_path / "artifact-second"
    second_artifact_directory.mkdir()
    second_archive = lifecycle.build_authority_promotion_bundle(
        receipt_path=receipt_path,
        artifact_directory=second_artifact_directory,
        build_receipt_path=tmp_path / "bundle-build-receipt-second.json",
        run_id=EXPECTED_RUN_ID,
        run_name=EXPECTED_RUN_NAME,
        artifact_name=EXPECTED_ARTIFACT_NAME,
        expected_source_revision=EXPECTED_REVISION,
        expected_api_revision=EXPECTED_REVISION,
        expected_web_revision=EXPECTED_REVISION,
    )
    assert second_archive.read_bytes() == archive_path.read_bytes()

    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        assert members[0].name == EMBEDDED_BUILD_RECEIPT
        embedded = archive.extractfile(members[0])
        assert embedded is not None
        embedded_payload = json.loads(embedded.read())
    assert embedded_payload["run_id"] == EXPECTED_RUN_ID
    assert embedded_payload["run_name"] == EXPECTED_RUN_NAME
    assert embedded_payload["artifact_name"] == EXPECTED_ARTIFACT_NAME
    assert embedded_payload["members"] == build_receipt["members"]


def _bundle_archive(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    source = tmp_path / "source"
    source.mkdir()
    payload = _promotion_receipt_payload(source)
    receipt_path = source / RECEIPT_NAME
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    download = tmp_path / "download"
    download.mkdir()
    archive_path = lifecycle.build_authority_promotion_bundle(
        receipt_path=receipt_path,
        artifact_directory=download,
        build_receipt_path=tmp_path / "bundle-build-receipt.json",
        run_id=EXPECTED_RUN_ID,
        run_name=EXPECTED_RUN_NAME,
        artifact_name=EXPECTED_ARTIFACT_NAME,
        expected_source_revision=EXPECTED_REVISION,
        expected_api_revision=EXPECTED_REVISION,
        expected_web_revision=EXPECTED_REVISION,
    )
    archived: dict[str, bytes] = {}
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive.getmembers():
            extracted = archive.extractfile(member)
            assert extracted is not None
            archived[member.name] = extracted.read()
    return download, archived


def _rewrite_archive(
    archive_path: Path,
    mutation: object,
) -> None:
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive.getmembers():
            extracted = archive.extractfile(member) if member.isfile() else None
            members.append((member, extracted.read() if extracted is not None else None))
    mutation(members)  # type: ignore[operator]
    with tarfile.open(archive_path, "w", format=tarfile.PAX_FORMAT) as archive:
        for member, data in members:
            member.size = len(data) if data is not None else 0
            archive.addfile(member, io.BytesIO(data) if data is not None else None)


def _stage(tmp_path: Path, *, expected_revision: str = EXPECTED_REVISION) -> tuple[Path, dict[str, bytes]]:
    download, archived = _bundle_archive(tmp_path)
    destination = tmp_path / "build-context-bundle"
    destination.mkdir()
    (destination / ".gitkeep").write_text("", encoding="utf-8")
    receipt_path = lifecycle.stage_authority_promotion_bundle(
        artifact_directory=download,
        destination_directory=destination,
        expected_source_revision=expected_revision,
        **_stage_identity(),
    )
    return receipt_path, archived


def test_stage_authority_promotion_bundle_preserves_exact_validated_transitive_files(
    tmp_path: Path,
) -> None:
    receipt_path, archived = _stage(tmp_path)

    assert receipt_path.name == RECEIPT_NAME
    assert not (receipt_path.parent / ".gitkeep").exists()
    staged = {
        str(INSTALL_DIRECTORY / path.relative_to(receipt_path.parent)): path.read_bytes()
        for path in receipt_path.parent.rglob("*")
        if path.is_file()
    }
    evidence_archived = {path: data for path, data in archived.items() if path != EMBEDDED_BUILD_RECEIPT}
    assert staged == evidence_archived
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in receipt_path.parent.rglob("*") if path.is_file())

    runtime_root = tmp_path / "runtime-root"
    runtime_bundle = runtime_root / Path(*INSTALL_DIRECTORY.parts)
    shutil.copytree(receipt_path.parent, runtime_bundle)
    receipt = lifecycle.load_authority_promotion_receipt(
        runtime_bundle / RECEIPT_NAME,
        filesystem_root=runtime_root,
    )
    assert receipt.jurisdiction_code == "WA"
    assert receipt.promotion_evidence.source_revision == EXPECTED_REVISION


def test_build_authority_promotion_bundle_refuses_extra_or_unsafe_rooted_source_files(
    tmp_path: Path,
) -> None:
    filesystem_root = tmp_path / "root"
    source = filesystem_root / Path(*INSTALL_DIRECTORY.parts)
    source.mkdir(parents=True)
    payload = _promotion_receipt_payload(source, reference_root=INSTALL_PATH)
    receipt_path = source / RECEIPT_NAME
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    extra = source / "unreferenced.json"
    extra.write_text("{}\n", encoding="utf-8")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()

    with pytest.raises(ValueError, match="rooted source file set mismatch"):
        lifecycle.build_authority_promotion_bundle(
            receipt_path=receipt_path,
            artifact_directory=artifact_directory,
            build_receipt_path=tmp_path / "build.json",
            run_id=EXPECTED_RUN_ID,
            run_name=EXPECTED_RUN_NAME,
            artifact_name=EXPECTED_ARTIFACT_NAME,
            expected_source_revision=EXPECTED_REVISION,
            expected_api_revision=EXPECTED_REVISION,
            expected_web_revision=EXPECTED_REVISION,
            filesystem_root=filesystem_root,
        )

    extra.unlink()
    unsafe = source / "unsafe.json"
    unsafe.symlink_to(receipt_path)
    with pytest.raises(ValueError, match="unsafe entries"):
        lifecycle.build_authority_promotion_bundle(
            receipt_path=receipt_path,
            artifact_directory=artifact_directory,
            build_receipt_path=tmp_path / "build.json",
            run_id=EXPECTED_RUN_ID,
            run_name=EXPECTED_RUN_NAME,
            artifact_name=EXPECTED_ARTIFACT_NAME,
            expected_source_revision=EXPECTED_REVISION,
            expected_api_revision=EXPECTED_REVISION,
            expected_web_revision=EXPECTED_REVISION,
            filesystem_root=filesystem_root,
        )


def test_lifecycle_cli_builds_rooted_authority_promotion_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    filesystem_root = tmp_path / "root"
    source = filesystem_root / Path(*INSTALL_DIRECTORY.parts)
    source.mkdir(parents=True)
    payload = _promotion_receipt_payload(source, reference_root=INSTALL_PATH)
    receipt_path = source / RECEIPT_NAME
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()
    build_receipt = tmp_path / "build-receipt.json"

    assert (
        lifecycle.main(
            [
                "--promotion-receipt-json",
                str(receipt_path),
                "--promotion-filesystem-root",
                str(filesystem_root),
                "--promotion-artifact-output-directory",
                str(artifact_directory),
                "--promotion-build-receipt-json",
                str(build_receipt),
                "--promotion-run-id",
                EXPECTED_RUN_ID,
                "--promotion-run-name",
                EXPECTED_RUN_NAME,
                "--promotion-artifact-name",
                EXPECTED_ARTIFACT_NAME,
                "--promotion-source-revision",
                EXPECTED_REVISION,
                "--promotion-api-revision",
                EXPECTED_REVISION,
                "--promotion-web-revision",
                EXPECTED_REVISION,
            ]
        )
        == 0
    )
    assert (artifact_directory / ARCHIVE_NAME).is_file()
    assert build_receipt.is_file()
    assert capsys.readouterr().out.startswith("Built validated authority promotion bundle:")


def test_build_authority_promotion_bundle_refuses_hardlinked_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = _promotion_receipt_payload(source)
    receipt_path = source / RECEIPT_NAME
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    hardlink = tmp_path / "candidate-receipt-hardlink.json"
    hardlink.hardlink_to(source / "candidate-receipt.json")
    artifact_directory = tmp_path / "artifact"
    artifact_directory.mkdir()

    with pytest.raises(ValueError, match="hardlinked evidence files"):
        lifecycle.build_authority_promotion_bundle(
            receipt_path=receipt_path,
            artifact_directory=artifact_directory,
            build_receipt_path=tmp_path / "build.json",
            run_id=EXPECTED_RUN_ID,
            run_name=EXPECTED_RUN_NAME,
            artifact_name=EXPECTED_ARTIFACT_NAME,
            expected_source_revision=EXPECTED_REVISION,
            expected_api_revision=EXPECTED_REVISION,
            expected_web_revision=EXPECTED_REVISION,
        )


def test_stage_authority_promotion_bundle_refuses_foreign_run_identity(tmp_path: Path) -> None:
    download, _ = _bundle_archive(tmp_path)
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="run or artifact identity mismatch"):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            expected_run_id="987654321",
            expected_run_name=EXPECTED_RUN_NAME,
            expected_artifact_name=EXPECTED_ARTIFACT_NAME,
        )


def test_stage_authority_promotion_bundle_is_atomic_on_validation_failure(tmp_path: Path) -> None:
    download, _ = _bundle_archive(tmp_path)
    archive_path = download / ARCHIVE_NAME

    def corrupt_receipt(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        for index, (member, data) in enumerate(members):
            if member.name.endswith(RECEIPT_NAME):
                assert data is not None
                payload = json.loads(data)
                payload["canonical_evidence"].reverse()
                members[index] = (member, (json.dumps(payload, sort_keys=True) + "\n").encode())
                return
        raise AssertionError("receipt member missing")

    _rewrite_archive(archive_path, corrupt_receipt)
    destination = tmp_path / "destination"
    destination.mkdir()
    sentinel = destination / ".gitkeep"
    sentinel.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="exact ordered canonical evidence"):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            **_stage_identity(),
        )

    assert list(destination.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("extra", "unreferenced"),
        ("missing", "regular non-symlink"),
        ("wrong_mode", "mode 0600"),
        ("special_mode", "mode 0600"),
        ("symlink", "regular files"),
        ("hardlink", "regular files"),
        ("traversal", "confined"),
        ("absolute", "relative"),
        ("duplicate", "duplicate"),
        ("reordered", "order or set mismatch"),
    ],
)
def test_stage_authority_promotion_bundle_rejects_unsafe_or_non_exact_archives(
    tmp_path: Path,
    case: str,
    error: str,
) -> None:
    download, _ = _bundle_archive(tmp_path)
    archive_path = download / ARCHIVE_NAME

    def mutate(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        if case == "extra":
            info = tarfile.TarInfo(str(INSTALL_DIRECTORY / "extra.json"))
            info.mode = 0o600
            members.append((info, b"{}\n"))
        elif case == "missing":
            members[:] = [row for row in members if not row[0].name.endswith("canary_ledger.json")]
        elif case == "wrong_mode":
            members[0][0].mode = 0o644
        elif case == "special_mode":
            members[0][0].mode = 0o4600
        elif case in {"symlink", "hardlink"}:
            info = tarfile.TarInfo(str(INSTALL_DIRECTORY / f"{case}.json"))
            info.type = tarfile.SYMTYPE if case == "symlink" else tarfile.LNKTYPE
            info.linkname = str(INSTALL_DIRECTORY / RECEIPT_NAME)
            info.mode = 0o600
            members.append((info, None))
        elif case == "traversal":
            members[0][0].name = "../escape.json"
        elif case == "absolute":
            members[0][0].name = "/app/private/civibus/authority-promotion/escape.json"
        elif case == "duplicate":
            original, data = members[0]
            duplicate = tarfile.TarInfo(original.name)
            duplicate.mode = original.mode
            members.append((duplicate, data))
        elif case == "reordered":
            members[1], members[2] = members[2], members[1]
        else:
            raise AssertionError(case)

    _rewrite_archive(archive_path, mutate)
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / ".gitkeep").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            **_stage_identity(),
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda receipt: receipt.update(api_revision="b" * 40), "revisions are split"),
        (lambda receipt: receipt["members"][0].update(sha256="0" * 64), "member identity mismatch"),
        (lambda receipt: receipt["members"].reverse(), "member identity mismatch"),
    ],
)
def test_stage_authority_promotion_bundle_refuses_split_or_drifted_embedded_build_receipt(
    tmp_path: Path,
    mutation: object,
    error: str,
) -> None:
    download, _ = _bundle_archive(tmp_path)
    archive_path = download / ARCHIVE_NAME

    def mutate_build_receipt(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        for index, (member, data) in enumerate(members):
            if member.name == EMBEDDED_BUILD_RECEIPT:
                assert data is not None
                payload = json.loads(data)
                mutation(payload)  # type: ignore[operator]
                members[index] = (member, (json.dumps(payload, sort_keys=True) + "\n").encode())
                return
        raise AssertionError("embedded build receipt member missing")

    _rewrite_archive(archive_path, mutate_build_receipt)
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match=error):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            **_stage_identity(),
        )


def test_stage_authority_promotion_bundle_rejects_stale_source_revision(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="serving source revision"):
        _stage(tmp_path, expected_revision="b" * 40)


@pytest.mark.parametrize(
    "credential_key",
    ("POSTGRES_PASSWORD", "api_token", "authorization", "private_key"),
)
def test_stage_authority_promotion_bundle_rejects_credential_bearing_raw_evidence(
    tmp_path: Path,
    credential_key: str,
) -> None:
    download, _ = _bundle_archive(tmp_path)
    archive_path = download / ARCHIVE_NAME

    def add_credential(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        for index, (member, _) in enumerate(members):
            if member.name.endswith("scheduled-database_observation.json"):
                members[index] = (member, json.dumps({credential_key: "must-not-ship"}).encode())
                return
        raise AssertionError("database observation member missing")

    _rewrite_archive(archive_path, add_credential)
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="credential-bearing key"):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            **_stage_identity(),
        )


@pytest.mark.parametrize("extra_name", ("extra.json", "nested/extra.json"))
def test_stage_authority_promotion_bundle_rejects_extra_downloaded_artifact_files(
    tmp_path: Path,
    extra_name: str,
) -> None:
    download, _ = _bundle_archive(tmp_path)
    extra = download / extra_name
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("extra\n", encoding="utf-8")
    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(ValueError, match="exactly one regular"):
        lifecycle.stage_authority_promotion_bundle(
            artifact_directory=download,
            destination_directory=destination,
            expected_source_revision=EXPECTED_REVISION,
            **_stage_identity(),
        )
