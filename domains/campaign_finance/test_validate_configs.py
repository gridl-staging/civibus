from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from domains.campaign_finance import validate_configs
from domains.campaign_finance.jurisdictions.config_schema import discover_jurisdiction_configs


ROOT_DIR = Path(__file__).resolve().parents[2]
JURISDICTIONS_DIR = ROOT_DIR / "domains" / "campaign_finance" / "jurisdictions"
CO_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "CO" / "config.yaml"
GA_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "GA" / "config.yaml"
NC_CONFIG_PATH = JURISDICTIONS_DIR / "states" / "NC" / "config.yaml"
_UNSET_PARENT = object()


def _mutate_and_write_config(
    source: Path,
    destination: Path,
    *,
    jurisdiction_code: str,
    jurisdiction_name: str,
    jurisdiction_parent: object = _UNSET_PARENT,
    source_url: str | None = None,
) -> Path:
    payload: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))
    jurisdiction = payload["jurisdiction"]
    jurisdiction["code"] = jurisdiction_code
    jurisdiction["name"] = jurisdiction_name

    if jurisdiction_parent is not _UNSET_PARENT:
        jurisdiction["parent"] = jurisdiction_parent

    if source_url is not None:
        for source in payload["data_sources"]:
            source["url"] = source_url

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return destination.resolve()


def test_main_validates_default_pilot_configs(capsys: pytest.CaptureFixture) -> None:
    exit_code = validate_configs.main()
    output = capsys.readouterr().out
    expected_paths = discover_jurisdiction_configs(JURISDICTIONS_DIR)

    assert exit_code == 0
    for path in expected_paths:
        assert f"PASS: {path}" in output
    assert "Validation summary: checked=" in output
    assert "failed=0" in output


def test_main_path_only_validates_requested_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config_payload: dict[str, Any] = yaml.safe_load(CO_CONFIG_PATH.read_text(encoding="utf-8"))
    for index, source in enumerate(config_payload["data_sources"], start=1):
        source["url"] = f"https://example.com/source-{index}"

    isolated_config_path = tmp_path / "isolated.yaml"
    isolated_config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    exit_code = validate_configs.main(["--path", str(isolated_config_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"PASS: {isolated_config_path}" in output
    assert "Validation summary: checked=1 passed=1 failed=0 warnings=0" in output


def test_main_invalid_config_reports_loader_error(capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    invalid_config = tmp_path / "invalid.yaml"
    invalid_config.write_text("jurisdiction: [\n", encoding="utf-8")

    exit_code = validate_configs.main(["--path", str(invalid_config)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert str(invalid_config) in output
    assert "Failed to parse YAML jurisdiction config" in output
    assert "line" in output.lower()


def test_main_verbose_prints_parsed_summary(capsys: pytest.CaptureFixture) -> None:
    non_verbose_exit_code = validate_configs.main(["--path", str(CO_CONFIG_PATH)])
    non_verbose_output = capsys.readouterr().out
    verbose_exit_code = validate_configs.main(["--path", str(CO_CONFIG_PATH), "--verbose"])
    verbose_output = capsys.readouterr().out

    assert non_verbose_exit_code == 0
    assert verbose_exit_code == 0
    assert non_verbose_output.count("PASS: ") == verbose_output.count("PASS: ")
    assert f"PASS: {CO_CONFIG_PATH}" in verbose_output
    assert "code=CO" in verbose_output
    assert "type=state" in verbose_output
    assert "parent=None" in verbose_output
    assert "source_count=3" in verbose_output


def test_main_reports_duplicate_jurisdiction_codes_without_failing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    first = _mutate_and_write_config(
        CO_CONFIG_PATH,
        tmp_path / "dup_one" / "config.yaml",
        jurisdiction_code="DUP",
        jurisdiction_name="Duplicate One",
        source_url="https://example.com/dup-one",
    )
    second = _mutate_and_write_config(
        GA_CONFIG_PATH,
        tmp_path / "dup_two" / "config.yaml",
        jurisdiction_code="DUP",
        jurisdiction_name="Duplicate Two",
        source_url="https://example.com/dup-two",
    )

    monkeypatch.setattr(validate_configs, "discover_jurisdiction_configs", lambda _base: [second, first])
    exit_code = validate_configs.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Duplicate jurisdiction code 'DUP'" in output


def test_main_reports_missing_parent_as_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    parent = _mutate_and_write_config(
        CO_CONFIG_PATH,
        tmp_path / "parent_present" / "config.yaml",
        jurisdiction_code="PARENT",
        jurisdiction_name="Parent Present",
        jurisdiction_parent=None,
        source_url="https://example.com/parent-present",
    )
    child = _mutate_and_write_config(
        GA_CONFIG_PATH,
        tmp_path / "parent_missing" / "config.yaml",
        jurisdiction_code="CHILD",
        jurisdiction_name="Child Missing",
        jurisdiction_parent="MISSING",
        source_url="https://example.com/parent-missing",
    )

    monkeypatch.setattr(validate_configs, "discover_jurisdiction_configs", lambda _base: [parent, child])
    exit_code = validate_configs.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Missing parent 'MISSING'" in output


def test_main_reports_duplicate_data_source_urls_without_failing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    first = _mutate_and_write_config(
        CO_CONFIG_PATH,
        tmp_path / "url_one" / "config.yaml",
        jurisdiction_code="URL1",
        jurisdiction_name="URL One",
        source_url="https://example.com/shared",
    )
    second = _mutate_and_write_config(
        GA_CONFIG_PATH,
        tmp_path / "url_two" / "config.yaml",
        jurisdiction_code="URL2",
        jurisdiction_name="URL Two",
        source_url="https://example.com/shared",
    )

    monkeypatch.setattr(validate_configs, "discover_jurisdiction_configs", lambda _base: [second, first])
    exit_code = validate_configs.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Duplicate data source URL 'https://example.com/shared'" in output
    assert str(first) in output
    assert str(second) in output


def test_main_reports_duplicate_data_source_urls_within_single_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    config_path = _mutate_and_write_config(
        CO_CONFIG_PATH,
        tmp_path / "url_repeat" / "config.yaml",
        jurisdiction_code="URL3",
        jurisdiction_name="URL Repeat",
        source_url="https://example.com/shared",
    )

    monkeypatch.setattr(validate_configs, "discover_jurisdiction_configs", lambda _base: [config_path])
    exit_code = validate_configs.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Duplicate data source URL 'https://example.com/shared'" in output
    assert str(config_path) in output


def test_main_output_is_deterministic_by_sorted_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    first = _mutate_and_write_config(
        CO_CONFIG_PATH,
        tmp_path / "zeta" / "config.yaml",
        jurisdiction_code="ZETA",
        jurisdiction_name="Zeta",
        source_url="https://example.com/zeta",
    )
    second = _mutate_and_write_config(
        GA_CONFIG_PATH,
        tmp_path / "alpha" / "config.yaml",
        jurisdiction_code="ALPHA",
        jurisdiction_name="Alpha",
        source_url="https://example.com/alpha",
    )
    third = _mutate_and_write_config(
        NC_CONFIG_PATH,
        tmp_path / "mu" / "config.yaml",
        jurisdiction_code="MU",
        jurisdiction_name="Mu",
        source_url="https://example.com/mu",
    )

    monkeypatch.setattr(validate_configs, "discover_jurisdiction_configs", lambda _base: [first, third, second])
    exit_code = validate_configs.main([])
    output = capsys.readouterr().out

    pass_paths = [line.removeprefix("PASS: ").strip() for line in output.splitlines() if line.startswith("PASS: ")]
    assert exit_code == 0
    assert pass_paths == sorted(pass_paths)
