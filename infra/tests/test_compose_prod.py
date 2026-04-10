"""Tests for the production Docker Compose configuration.

Validates that infra/docker-compose.prod.yml:
- Parses without errors via both PyYAML and `docker compose config`
- Declares exactly 3 services: db, api, web
- No service binds host ports to all interfaces (`0.0.0.0`)
- api and web declare depends_on with health check conditions
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import yaml
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.prod.yml"
DEPLOY_WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
BOOTSTRAP_SCRIPT_FILE = REPO_ROOT / "infra" / "scripts" / "bootstrap_prod_vm.sh"
AGE_BOOTSTRAP_SQL_FILE = REPO_ROOT / "infra" / "db" / "09-age-graph-bootstrap.sql"
_EXPECTED_DB_INIT_MOUNTS = [
    "../core/schema/entities.sql:/docker-entrypoint-initdb.d/01-entities.sql",
    "../core/schema/jurisdiction.sql:/docker-entrypoint-initdb.d/02-jurisdiction.sql",
    "../core/schema/provenance.sql:/docker-entrypoint-initdb.d/03-provenance.sql",
    "../core/schema/entity_resolution.sql:/docker-entrypoint-initdb.d/04-entity_resolution.sql",
    "../core/schema/er_views.sql:/docker-entrypoint-initdb.d/05-er_views.sql",
    "../domains/campaign_finance/schema/tables.sql:/docker-entrypoint-initdb.d/06-campaign-finance.sql",
    "../domains/campaign_finance/schema/dark_money_tables.sql:/docker-entrypoint-initdb.d/07-dark-money.sql",
    "../domains/property/schema/tables.sql:/docker-entrypoint-initdb.d/08-property.sql",
    "../domains/civics/schema/tables.sql:/docker-entrypoint-initdb.d/09-civics.sql",
    "../infra/db/09-age-graph-bootstrap.sql:/docker-entrypoint-initdb.d/10-age-graph-bootstrap.sql",
]

# Representative env vars for compose config validation.
# These satisfy all required interpolations (e.g. ${POSTGRES_PASSWORD:?...}).
_COMPOSE_CONFIG_ENV = {
    "POSTGRES_PASSWORD": "test-compose-config-pw",
    "ORIGIN": "https://test.civibus.example.com",
    "CIVIBUS_API_KEYS": "test-key-1",
    "CIVIBUS_ADMIN_API_KEYS": "test-admin-key-1",
    "CIVIBUS_RATE_LIMIT_REQUESTS": "321",
    "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS": "654",
    "CIVIBUS_API_KEY": "test-web-key",
}


def _port_mapping_binds_all_interfaces(port_mapping: str | dict) -> bool:
    """Return True when a compose port mapping would publish on all host interfaces."""
    if isinstance(port_mapping, dict):
        host_ip = port_mapping.get("host_ip")
        if host_ip == "0.0.0.0":
            return True
        if host_ip:
            return False

        published_port = port_mapping.get("published")
        if published_port is None:
            return False

        # Keep the existing Stage 2 allowance for variable-interpolated host ports.
        return "$" not in str(published_port)

    mapping_text = str(port_mapping)
    mapping_parts = mapping_text.split(":")

    if len(mapping_parts) >= 3:
        return mapping_parts[0] == "0.0.0.0"

    if len(mapping_parts) == 2:
        host_port = mapping_parts[0]
        # Keep the existing Stage 2 allowance for variable-interpolated host ports.
        return "$" not in host_port

    # A single published port also uses Docker's default all-interface bind.
    return True


def _run_compose_config(
    *,
    env_updates: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `docker compose config` with representative env vars for this stack."""
    env = {
        **_COMPOSE_CONFIG_ENV,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    for env_var_name, env_var_value in (env_updates or {}).items():
        if env_var_value is None:
            env.pop(env_var_name, None)
        else:
            env[env_var_name] = env_var_value

    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _docker_compose_available() -> bool:
    """Return True when the docker CLI and compose subcommand are both usable."""
    if shutil.which("docker") is None:
        return False

    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


_has_docker_compose = _docker_compose_available()


@pytest.fixture(scope="module")
def compose_config() -> dict:
    """Parse the production compose file via PyYAML for structural assertions."""
    assert COMPOSE_FILE.exists(), f"Missing {COMPOSE_FILE}"
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


def test_compose_file_exists():
    assert COMPOSE_FILE.exists(), f"Expected {COMPOSE_FILE} to exist"


def test_declares_exactly_three_services(compose_config: dict):
    services = set(compose_config.get("services", {}).keys())
    assert services == {"db", "api", "web"}, f"Expected {{db, api, web}}, got {services}"


def test_api_and_web_have_ghcr_image_fields(compose_config: dict):
    """api and web must include GHCR image refs with an overrideable deploy tag."""
    ghcr_prefix = "ghcr.io/gridl-dev/civibus_dev/"
    services = compose_config["services"]
    for service_name in ("api", "web"):
        image_value = services[service_name].get("image")
        assert image_value, f"{service_name} service must declare an image field"
        assert ghcr_prefix in image_value, (
            f"{service_name} image must include GHCR prefix {ghcr_prefix!r}, got {image_value!r}"
        )
        expected_image = f"{ghcr_prefix}{service_name}:${{IMAGE_TAG:-latest}}"
        assert image_value == expected_image, (
            f"{service_name} image must default to latest while allowing IMAGE_TAG override; "
            f"expected {expected_image!r}, got {image_value!r}"
        )


def test_no_service_binds_to_all_interfaces(compose_config: dict):
    """No service should publish host ports to 0.0.0.0."""
    services = compose_config["services"]
    for service_name, service_config in services.items():
        for port_mapping in service_config.get("ports", []):
            assert not _port_mapping_binds_all_interfaces(port_mapping), (
                f"{service_name} must not bind ports to all interfaces: {port_mapping!r}"
            )


def test_db_exposes_localhost_only_port(compose_config: dict):
    db_ports = compose_config["services"]["db"].get("ports")
    assert db_ports == ["127.0.0.1:5432:5432"], (
        "db service must expose exactly localhost-only 5432 mapping for host-side ingest commands"
    )


def test_db_bootstrap_includes_domain_schemas_and_age_graph(compose_config: dict):
    """First-run init must load core/domain schemas and one-time AGE graph bootstrap."""
    db_volumes = compose_config["services"]["db"].get("volumes", [])
    mounted_init_entries = [entry for entry in db_volumes if isinstance(entry, str) and "initdb.d" in entry]
    assert mounted_init_entries == _EXPECTED_DB_INIT_MOUNTS, (
        "db init mounts must deterministically load core SQL, campaign_finance/property "
        "domain schemas, and one-time AGE graph bootstrap artifact"
    )


def test_age_bootstrap_sql_is_idempotent_and_self_bootstrapping():
    """AGE bootstrap SQL must be safe on first deploy and graph creation retry."""
    assert AGE_BOOTSTRAP_SQL_FILE.exists(), f"Expected {AGE_BOOTSTRAP_SQL_FILE} to exist"
    sql_text = AGE_BOOTSTRAP_SQL_FILE.read_text().lower()

    assert "create extension if not exists age" in sql_text, (
        "AGE bootstrap SQL must ensure extension installation in the same init artifact"
    )
    assert "if not exists (select 1 from ag_catalog.ag_graph where name = 'civibus')" in sql_text, (
        "AGE bootstrap SQL must guard civibus graph creation with NOT EXISTS"
    )
    assert "perform ag_catalog.create_graph('civibus')" in sql_text, (
        "AGE bootstrap SQL must create the civibus graph when missing"
    )


@pytest.mark.parametrize(
    ("port_mapping", "expected_all_interface_bind"),
    [
        ("127.0.0.1:5432:5432", False),
        ("0.0.0.0:5432:5432", True),
        ("5432:5432", True),
        ("${WEB_PORT:-3000}:3000", False),
        ({"host_ip": "127.0.0.1", "published": "5432", "target": 5432}, False),
        ({"published": "5432", "target": 5432}, True),
    ],
)
def test_port_binding_policy_flags_implicit_all_interface_binds(
    port_mapping: str | dict,
    expected_all_interface_bind: bool,
):
    """Guard the helper logic behind the Stage 2 host-port policy."""
    assert _port_mapping_binds_all_interfaces(port_mapping) is expected_all_interface_bind


def test_api_depends_on_db_healthy(compose_config: dict):
    api_deps = compose_config["services"]["api"].get("depends_on", {})
    assert "db" in api_deps, "api must depend on db"
    assert api_deps["db"].get("condition") == "service_healthy", "api must wait for db to be healthy"


def test_web_depends_on_api_healthy(compose_config: dict):
    web_deps = compose_config["services"]["web"].get("depends_on", {})
    assert "api" in web_deps, "web must depend on api"
    assert web_deps["api"].get("condition") == "service_healthy", "web must wait for api to be healthy"


def test_db_has_healthcheck(compose_config: dict):
    db_svc = compose_config["services"]["db"]
    assert "healthcheck" in db_svc, "db service must have a healthcheck"


def test_api_has_healthcheck(compose_config: dict):
    api_svc = compose_config["services"]["api"]
    assert "healthcheck" in api_svc, "api service must have a healthcheck"


def test_all_services_on_civibus_network(compose_config: dict):
    """All services must be attached to the civibus bridge network."""
    networks = compose_config.get("networks", {})
    assert "civibus" in networks, "Must define a 'civibus' network"

    for name, svc in compose_config["services"].items():
        svc_networks = svc.get("networks", [])
        assert "civibus" in svc_networks, f"{name} must be on civibus network"


def test_api_environment_has_production_settings(compose_config: dict):
    """API service must set CIVIBUS_ENV=production and correct DB connection vars."""
    api_env = compose_config["services"]["api"].get("environment", {})
    assert api_env.get("CIVIBUS_ENV") == "production"
    assert api_env.get("POSTGRES_HOST") == "db"
    # POSTGRES_PORT should be 5432 (int or string) for container networking
    port_val = api_env.get("POSTGRES_PORT")
    assert str(port_val) == "5432", f"Expected POSTGRES_PORT=5432, got {port_val}"


def test_web_environment_has_api_base_url(compose_config: dict):
    web_env = compose_config["services"]["web"].get("environment", {})
    assert web_env.get("CIVIBUS_API_BASE_URL") == "http://api:8000"
    assert web_env.get("NODE_ENV") == "production"


def test_env_production_example_exists():
    env_example = REPO_ROOT / ".env.production.example"
    assert env_example.exists(), f"Expected {env_example} to exist"


def test_env_production_example_documents_required_vars():
    """The env example must mention all deployment-controlled variables."""
    env_example = REPO_ROOT / ".env.production.example"
    content = env_example.read_text()

    required_vars = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "CIVIBUS_API_KEYS",
        "CIVIBUS_ADMIN_API_KEYS",
        "CIVIBUS_RATE_LIMIT_REQUESTS",
        "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS",
        "ORIGIN",
        "WEB_PORT",
        "CIVIBUS_API_KEY",
    ]
    for var in required_vars:
        assert var in content, f".env.production.example must document {var}"


def test_env_production_example_documents_explicit_env_file_usage():
    """Docs must use --env-file so root `.env` works with infra compose path."""
    env_example = REPO_ROOT / ".env.production.example"
    content = env_example.read_text()
    expected_command = "docker compose --env-file .env -f infra/docker-compose.prod.yml up"
    assert expected_command in content, (
        ".env.production.example must document compose usage with explicit --env-file .env "
        "when using -f infra/docker-compose.prod.yml"
    )


def _load_deploy_workflow() -> tuple[str, dict]:
    """Return the raw workflow text plus parsed YAML for deploy contract assertions."""
    assert DEPLOY_WORKFLOW_FILE.exists(), f"Expected {DEPLOY_WORKFLOW_FILE} to exist"
    workflow_text = DEPLOY_WORKFLOW_FILE.read_text()
    return workflow_text, yaml.safe_load(workflow_text)


def _workflow_triggers(workflow_config: dict) -> dict:
    """Return the 'on' block, handling PyYAML's bare ``on:`` → True key coercion."""
    return workflow_config.get("on", workflow_config.get(True, {}))


def _deploy_ssh_rollout_run(workflow_config: dict) -> str:
    """Return the only SSH rollout script defined under jobs.deploy."""
    deploy_steps = workflow_config["jobs"]["deploy"].get("steps", [])
    ssh_rollout_steps = [
        step
        for step in deploy_steps
        if isinstance(step, dict) and step.get("name") == "Roll out api and web via remote compose"
    ]
    assert len(ssh_rollout_steps) == 1, "deploy job must define exactly one SSH remote command block"
    return ssh_rollout_steps[0]["run"]


def _deploy_bootstrap_run(workflow_config: dict) -> str:
    """Return the only remote bootstrap script defined under jobs.deploy."""
    deploy_steps = workflow_config["jobs"]["deploy"].get("steps", [])
    bootstrap_steps = [
        step
        for step in deploy_steps
        if isinstance(step, dict) and step.get("name") == "Bootstrap remote host prerequisites"
    ]
    assert len(bootstrap_steps) == 1, "deploy job must define exactly one bootstrap step"
    return bootstrap_steps[0]["run"]


def test_deploy_workflow_replaces_placeholder_with_ssh_compose_rollout():
    workflow_text, workflow_config = _load_deploy_workflow()

    assert "Deploy placeholder" not in workflow_text, (
        "deploy workflow must remove placeholder message and run the real rollout"
    )

    rollout_run = _deploy_ssh_rollout_run(workflow_config)
    expected_command_sequence = [
        "cd /root/civibus/civibus_dev",
        "docker compose --env-file .env -f infra/docker-compose.prod.yml pull api web",
        "docker compose --env-file .env -f infra/docker-compose.prod.yml up -d api web",
    ]
    for expected_command in expected_command_sequence:
        assert expected_command in rollout_run, f"deploy SSH rollout command block must include {expected_command!r}"

    assert "fetch origin " in rollout_run, "deploy SSH rollout command block must refresh the VM checkout"
    assert rollout_run.index("fetch origin ") < rollout_run.index(
        "docker compose --env-file .env -f infra/docker-compose.prod.yml pull api web"
    ), "deploy SSH rollout must refresh the checkout before compose pull"
    command_order_indexes = [rollout_run.index(command) for command in expected_command_sequence]
    assert command_order_indexes == sorted(command_order_indexes), (
        "deploy SSH rollout must run repo sync before compose pull, then compose up"
    )
    assert "docker pull ghcr.io/" not in workflow_text, (
        "workflow must avoid duplicating raw GHCR docker pull commands and rely on compose"
    )


def test_deploy_workflow_uses_github_secrets_not_runtime_env_file():
    workflow_text, _ = _load_deploy_workflow()
    env_example = REPO_ROOT / ".env.production.example"
    env_example_text = env_example.read_text()

    assert "secrets.HETZNER_HOST" in workflow_text, (
        "deploy workflow must read host connection endpoint from secrets.HETZNER_HOST"
    )
    assert "secrets.HETZNER_SSH_KEY" in workflow_text, (
        "deploy workflow must read private key material from secrets.HETZNER_SSH_KEY"
    )
    assert "secrets.HETZNER_KNOWN_HOSTS" in workflow_text, (
        "deploy workflow must read the pinned host key from secrets.HETZNER_KNOWN_HOSTS"
    )
    assert "secrets.PRODUCTION_ENV_FILE" in workflow_text, (
        "deploy workflow must read the production .env payload from secrets.PRODUCTION_ENV_FILE"
    )
    for secret_name in (
        "HETZNER_HOST",
        "HETZNER_SSH_KEY",
        "HETZNER_KNOWN_HOSTS",
        "PRODUCTION_ENV_FILE",
    ):
        assert secret_name not in env_example_text, (
            f".env.production.example must not include CI-only deploy secret {secret_name}"
        )


def test_deploy_workflow_pins_remote_checkout_to_trigger_sha():
    workflow_text, workflow_config = _load_deploy_workflow()
    rollout_run = _deploy_ssh_rollout_run(workflow_config)
    deploy_env = workflow_config["jobs"]["deploy"].get("env", {})

    assert deploy_env.get("DEPLOY_GIT_SHA") == "${{ github.sha }}", (
        "deploy workflow must pass the triggering commit SHA into the remote rollout"
    )

    expected_command_sequence = [
        'ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=~/.ssh/known_hosts -i ~/.ssh/hetzner_deploy_key "root@${HETZNER_HOST}" bash -se -- "$DEPLOY_GIT_SHA" "$GITHUB_TOKEN" "$GITHUB_ACTOR" <<\'EOF\'',
        'deploy_git_sha="$1"',
        'fetch origin "$deploy_git_sha"',
        'git checkout --detach "$deploy_git_sha"',
        'export IMAGE_TAG="$deploy_git_sha"',
        "docker compose --env-file .env -f infra/docker-compose.prod.yml pull api web",
        "docker compose --env-file .env -f infra/docker-compose.prod.yml up -d api web",
    ]
    for expected_command in expected_command_sequence:
        assert expected_command in rollout_run, f"deploy SSH rollout command block must include {expected_command!r}"

    for forbidden_command in ("git pull --ff-only origin main", "git fetch origin main\n"):
        assert forbidden_command not in rollout_run, (
            "deploy workflow must not sync the VM checkout to the mutable branch tip"
        )

    command_order_indexes = [rollout_run.index(command) for command in expected_command_sequence]
    assert command_order_indexes == sorted(command_order_indexes), (
        "deploy SSH rollout must pin the checkout before compose pull and compose up"
    )


def test_deploy_workflow_bootstraps_the_remote_host_before_rollout() -> None:
    workflow_text, workflow_config = _load_deploy_workflow()
    deploy_env = workflow_config["jobs"]["deploy"].get("env", {})
    bootstrap_run = _deploy_bootstrap_run(workflow_config)

    assert deploy_env.get("PRODUCTION_ENV_FILE") == "${{ secrets.PRODUCTION_ENV_FILE }}", (
        "deploy workflow must inject the production .env payload via CI secrets"
    )
    expected_bootstrap_fragments = [
        "install -m 600 /dev/null /tmp/civibus-production.env",
        "printf '%s\\n' \"$PRODUCTION_ENV_FILE\" > /tmp/civibus-production.env",
        'infra/scripts/bootstrap_prod_vm.sh /tmp/civibus-production.env "root@${HETZNER_HOST}:/tmp/civibus-deploy/"',
        'export REPO_URL="$deploy_repo_url"',
        'export REPO_DIR="/root/civibus/civibus_dev"',
        'export ENV_FILE_SOURCE="/tmp/civibus-deploy/civibus-production.env"',
        "bash /tmp/civibus-deploy/bootstrap_prod_vm.sh",
    ]
    for fragment in expected_bootstrap_fragments:
        assert fragment in bootstrap_run, f"bootstrap step must include {fragment!r}"

    assert "Bootstrap remote host prerequisites" in workflow_text, (
        "deploy workflow must define an explicit bootstrap phase before rollout"
    )


def test_bootstrap_script_installs_prereqs_and_materializes_env_file() -> None:
    assert BOOTSTRAP_SCRIPT_FILE.exists(), f"Expected {BOOTSTRAP_SCRIPT_FILE} to exist"
    script_text = BOOTSTRAP_SCRIPT_FILE.read_text()

    required_fragments = [
        'repo_dir="${REPO_DIR:-/root/civibus/civibus_dev}"',
        'repo_url="${REPO_URL:-https://github.com/gridl-dev/civibus_dev.git}"',
        'env_file_source="${ENV_FILE_SOURCE:-}"',
        "apt-get install -y ca-certificates curl git gnupg",
        "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
        'git clone "${repo_url}" "${repo_dir}"',
        'install -m 0600 "${env_file_source}" "${repo_dir}/.env"',
        'grep -Eq "^${required_key}=.+$" "${env_file}"',
        "docker compose version >/dev/null",
    ]
    for fragment in required_fragments:
        assert fragment in script_text, f"bootstrap script must include {fragment!r}"


def test_deploy_workflow_pins_the_remote_host_key() -> None:
    workflow_text, workflow_config = _load_deploy_workflow()
    deploy_env = workflow_config["jobs"]["deploy"].get("env", {})
    rollout_run = _deploy_ssh_rollout_run(workflow_config)

    assert deploy_env.get("HETZNER_KNOWN_HOSTS") == "${{ secrets.HETZNER_KNOWN_HOSTS }}", (
        "deploy workflow must inject the pinned known_hosts entry via CI secrets"
    )
    assert "printf '%s\\n' \"$HETZNER_KNOWN_HOSTS\" > ~/.ssh/known_hosts" in workflow_text, (
        "deploy workflow must write the pinned known_hosts entry before SSH"
    )
    assert "StrictHostKeyChecking=accept-new" not in workflow_text, (
        "deploy workflow must not trust-first-use a production SSH host key"
    )
    assert "StrictHostKeyChecking=yes" in rollout_run, (
        "deploy workflow must enforce host-key verification during SSH rollout"
    )
    assert "UserKnownHostsFile=~/.ssh/known_hosts" in rollout_run, (
        "deploy workflow must point SSH at the pinned known_hosts file"
    )


def test_deploy_workflow_has_workflow_dispatch_trigger():
    """Deploy workflow must support manual triggering via workflow_dispatch."""
    _, workflow_config = _load_deploy_workflow()
    triggers = _workflow_triggers(workflow_config)
    assert "workflow_dispatch" in triggers, (
        "deploy workflow must include workflow_dispatch trigger for manual deploys via 'gh workflow run'"
    )
    assert "push" in triggers, "deploy workflow must retain push trigger alongside workflow_dispatch"


def test_deploy_workflow_authenticates_private_repo_access():
    """Deploy workflow must authenticate git and GHCR access for private repos.

    Three requirements:
    (a) GITHUB_TOKEN in deploy job env for shell-level access
    (b) Rollout step: authenticated git fetch + docker login ghcr.io before compose pull
    (c) Bootstrap step: DEPLOY_REPO_URL uses token-authenticated HTTPS for fresh clones
    """
    _, workflow_config = _load_deploy_workflow()
    deploy_env = workflow_config["jobs"]["deploy"].get("env", {})

    # (a) GITHUB_TOKEN must be in deploy job env
    assert "GITHUB_TOKEN" in deploy_env, "deploy job must expose GITHUB_TOKEN in env for private repo auth"

    # (c) DEPLOY_REPO_URL must use token-authenticated URL for bootstrap clones
    repo_url = deploy_env.get("DEPLOY_REPO_URL", "")
    assert "x-access-token" in repo_url, "DEPLOY_REPO_URL must use x-access-token auth for private repo clones"

    # (b) Rollout step must authenticate git fetch and docker login before compose pull
    rollout_run = _deploy_ssh_rollout_run(workflow_config)
    assert "docker login ghcr.io" in rollout_run, "rollout step must docker login to GHCR before pulling private images"
    assert "insteadOf" in rollout_run, "rollout step must use git insteadOf to authenticate fetch for private repos"

    # docker login must come before docker compose pull
    login_pos = rollout_run.index("docker login ghcr.io")
    pull_pos = rollout_run.index("docker compose --env-file .env -f infra/docker-compose.prod.yml pull api web")
    assert login_pos < pull_pos, "rollout step must docker login before docker compose pull"


# ---------------------------------------------------------------------------
# docker compose config integration tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_docker_compose, reason="docker not on PATH")
class TestComposeConfig:
    """Run `docker compose config` to catch interpolation and parser regressions."""

    @pytest.fixture(scope="class")
    def resolved_config(self) -> dict:
        """Invoke `docker compose config` and return the parsed YAML output."""
        result = _run_compose_config()
        assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"
        return json.loads(result.stdout)

    def test_compose_config_resolves_without_errors(self, resolved_config: dict):
        assert "services" in resolved_config

    def test_resolved_api_env_interpolation(self, resolved_config: dict):
        """Verify compose interpolated env vars into the api service."""
        api_env = resolved_config["services"]["api"]["environment"]
        assert api_env["CIVIBUS_ENV"] == "production"
        assert api_env["POSTGRES_HOST"] == "db"
        assert api_env["POSTGRES_PORT"] == "5432"
        assert api_env["POSTGRES_PASSWORD"] == "test-compose-config-pw"
        assert api_env["CIVIBUS_CORS_ORIGIN"] == "https://test.civibus.example.com"
        assert api_env["CIVIBUS_API_KEYS"] == "test-key-1"
        assert api_env["CIVIBUS_ADMIN_API_KEYS"] == "test-admin-key-1"
        assert api_env["CIVIBUS_RATE_LIMIT_REQUESTS"] == "321"
        assert api_env["CIVIBUS_RATE_LIMIT_WINDOW_SECONDS"] == "654"

    def test_resolved_web_env_interpolation(self, resolved_config: dict):
        """Verify compose interpolated env vars into the web service."""
        web_env = resolved_config["services"]["web"]["environment"]
        assert web_env["CIVIBUS_API_BASE_URL"] == "http://api:8000"
        assert web_env["NODE_ENV"] == "production"
        assert web_env["ORIGIN"] == "https://test.civibus.example.com"
        assert web_env["PUBLIC_ORIGIN"] == "https://test.civibus.example.com"
        assert web_env["CIVIBUS_API_KEY"] == "test-web-key"

    def test_resolved_api_healthcheck_uses_python(self, resolved_config: dict):
        """Healthcheck must use python3 (not curl) — regression guard."""
        api_hc = resolved_config["services"]["api"]["healthcheck"]["test"]
        # CMD-SHELL format: ["CMD-SHELL", "command string"]
        cmd = api_hc[-1] if isinstance(api_hc, list) else api_hc
        assert "python3" in cmd, f"API healthcheck must use python3, got: {cmd}"
        assert "curl" not in cmd, f"API healthcheck must not use curl, got: {cmd}"

    @pytest.mark.parametrize(
        "missing_env_var_name",
        [
            "POSTGRES_PASSWORD",
            "ORIGIN",
            "CIVIBUS_API_KEYS",
            "CIVIBUS_ADMIN_API_KEYS",
            "CIVIBUS_API_KEY",
        ],
    )
    def test_compose_config_requires_critical_env_vars(self, missing_env_var_name: str):
        """Missing production env vars must fail at compose-config time, not runtime."""
        result = _run_compose_config(env_updates={missing_env_var_name: None})
        output = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0, (
            f"docker compose config must fail when {missing_env_var_name} is missing; output was:\n{output}"
        )
        assert missing_env_var_name in output, (
            f"docker compose config error output must mention {missing_env_var_name}; output was:\n{output}"
        )
