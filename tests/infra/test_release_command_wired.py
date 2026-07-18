"""Contract test for the API Fly release command."""

from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]
API_FLY_CONFIG_PATH = REPO_ROOT / "infra/fly/api.fly.toml"


def test_api_fly_release_command_runs_schema_migration_runner() -> None:
    payload = tomllib.loads(API_FLY_CONFIG_PATH.read_text(encoding="utf-8"))

    assert payload["deploy"]["release_command"] == "python -m core.schema.apply_migrations"
